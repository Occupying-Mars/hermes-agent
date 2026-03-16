#ifdef _WIN32

#include <napi.h>

void StartKeyloggerWin(const Napi::CallbackInfo& info) {
  Napi::Error::New(info.Env(), "autoclys observation keylogger is not implemented for windows yet")
      .ThrowAsJavaScriptException();
}

void StopKeyloggerWin(const Napi::CallbackInfo& info) {
  (void)info;
}

Napi::String GetActiveWindowWin(const Napi::CallbackInfo& info) {
  return Napi::String::New(info.Env(), "unsupported");
}

#endif
