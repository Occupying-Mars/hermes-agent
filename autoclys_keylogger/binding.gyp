{
  "targets": [
    {
      "target_name": "keylogger",
      "sources": [
        "native/keylogger.cc",
        "native/keylogger_mac.mm",
        "native/keylogger_win.cc",
        "native/keylogger_linux.cc"
      ],
      "include_dirs": [
        "<!@(node -p \"require('node-addon-api').include\")",
        "<!@(node -p \"require('nan').include_dirs\")"
      ],
      "defines": [ "NAPI_DISABLE_CPP_EXCEPTIONS" ],
      "cflags!": [ "-fno-exceptions" ],
      "cflags_cc!": [ "-fno-exceptions" ],
      "conditions": [
        [
          "OS==\"mac\"",
          {
            "sources": [ "native/keylogger_mac.mm" ],
            "link_settings": {
              "libraries": [
                "-framework AppKit",
                "-framework Carbon",
                "-framework CoreFoundation"
              ]
            },
            "xcode_settings": {
              "GCC_ENABLE_CPP_EXCEPTIONS": "YES",
              "CLANG_CXX_LIBRARY": "libc++",
              "MACOSX_DEPLOYMENT_TARGET": "10.15"
            }
          }
        ],
        [
          "OS==\"win\"",
          {
            "sources": [ "native/keylogger_win.cc" ],
            "libraries": [ "user32.lib" ]
          }
        ],
        [
          "OS==\"linux\"",
          {
            "sources": [ "native/keylogger_linux.cc" ],
            "libraries": [ "-lX11" ]
          }
        ]
      ]
    }
  ]
}
