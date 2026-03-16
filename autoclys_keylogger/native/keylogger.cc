#include <iostream>
#include <napi.h>

void StartKeyloggerMac(const Napi::CallbackInfo& info);
void StopKeyloggerMac(const Napi::CallbackInfo& info);
Napi::String GetActiveWindowMac(const Napi::CallbackInfo& info);

void StartKeyloggerWin(const Napi::CallbackInfo& info);
void StopKeyloggerWin(const Napi::CallbackInfo& info);
Napi::String GetActiveWindowWin(const Napi::CallbackInfo& info);

void StartKeyloggerLinux(const Napi::CallbackInfo& info);
void StopKeyloggerLinux(const Napi::CallbackInfo& info);
Napi::String GetActiveWindowLinux(const Napi::CallbackInfo& info);

#if defined(__APPLE__)
  #define IS_MAC 1
  #define IS_WIN 0
  #define IS_LINUX 0
#elif defined(_WIN32) || defined(_WIN64)
  #define IS_MAC 0
  #define IS_WIN 1
  #define IS_LINUX 0
#elif defined(__linux__)
  #define IS_MAC 0
  #define IS_WIN 0
  #define IS_LINUX 1
#else
  #define IS_MAC 0
  #define IS_WIN 0
  #define IS_LINUX 0
#endif

void StartKeylogger(const Napi::CallbackInfo& info) {
  Napi::Env env = info.Env();
  try {
#if IS_MAC
    StartKeyloggerMac(info);
#elif IS_WIN
    StartKeyloggerWin(info);
#elif IS_LINUX
    StartKeyloggerLinux(info);
#else
    Napi::Error::New(env, "unsupported platform").ThrowAsJavaScriptException();
#endif
  } catch (const std::exception& err) {
    Napi::Error::New(env, err.what()).ThrowAsJavaScriptException();
  }
}

void StopKeylogger(const Napi::CallbackInfo& info) {
  Napi::Env env = info.Env();
  try {
#if IS_MAC
    StopKeyloggerMac(info);
#elif IS_WIN
    StopKeyloggerWin(info);
#elif IS_LINUX
    StopKeyloggerLinux(info);
#else
    Napi::Error::New(env, "unsupported platform").ThrowAsJavaScriptException();
#endif
  } catch (const std::exception& err) {
    Napi::Error::New(env, err.what()).ThrowAsJavaScriptException();
  }
}

Napi::String GetActiveWindow(const Napi::CallbackInfo& info) {
  Napi::Env env = info.Env();
  try {
#if IS_MAC
    return GetActiveWindowMac(info);
#elif IS_WIN
    return GetActiveWindowWin(info);
#elif IS_LINUX
    return GetActiveWindowLinux(info);
#else
    return Napi::String::New(env, "unsupported platform");
#endif
  } catch (const std::exception& err) {
    return Napi::String::New(env, std::string("error: ") + err.what());
  }
}

Napi::Object Init(Napi::Env env, Napi::Object exports) {
  exports.Set("startKeylogger", Napi::Function::New(env, StartKeylogger));
  exports.Set("stopKeylogger", Napi::Function::New(env, StopKeylogger));
  exports.Set("getActiveWindow", Napi::Function::New(env, GetActiveWindow));
  return exports;
}

NODE_API_MODULE(keylogger, Init)
