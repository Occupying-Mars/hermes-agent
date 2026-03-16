const path = require('path');
const EventEmitter = require('events');

function loadNativeModule() {
  const modulePath = path.join(__dirname, '..', 'build', 'Release', 'keylogger.node');
  try {
    return require(modulePath);
  } catch (error) {
    const detail = error && error.message ? error.message : String(error);
    throw new Error(
      `autoclys keylogger native addon is unavailable at ${modulePath}. run \`npm --prefix autoclys_keylogger install\` to build it. ${detail}`
    );
  }
}

const nativeModule = loadNativeModule();

class KeyLogger extends EventEmitter {
  constructor() {
    super();
    this.isRunning = false;
    this.windowBuffers = new Map();
    this.keyDebounceTime = 1000;
    this.keystrokeCallback = this.keystrokeCallback.bind(this);
  }

  start() {
    if (this.isRunning) {
      return true;
    }

    try {
      nativeModule.startKeylogger(this.keystrokeCallback);
      this.isRunning = true;
      this.emit('start');
      this.bufferTimer = setInterval(() => {
        this.checkBuffers();
      }, 500);
      return true;
    } catch (error) {
      this.emit('error', error);
      return false;
    }
  }

  stop() {
    if (!this.isRunning) {
      return true;
    }

    try {
      nativeModule.stopKeylogger();
      this.isRunning = false;
      this.emit('stop');
      if (this.bufferTimer) {
        clearInterval(this.bufferTimer);
        this.bufferTimer = null;
      }
      return true;
    } catch (error) {
      this.emit('error', error);
      return false;
    }
  }

  getActiveWindow() {
    try {
      return nativeModule.getActiveWindow();
    } catch (error) {
      this.emit('error', error);
      return 'Unknown';
    }
  }

  keystrokeCallback(data) {
    try {
      const key = data.key;
      const window = data.window;
      const now = Date.now();

      if (!this.windowBuffers.has(window)) {
        this.windowBuffers.set(window, {
          buffer: '',
          lastKeyTime: now,
        });
      }

      const bufferData = this.windowBuffers.get(window);
      const timeSinceLastKey = now - bufferData.lastKeyTime;
      this.processKeystroke(key, window, bufferData, timeSinceLastKey);
      bufferData.lastKeyTime = now;

      this.emit('keystroke', { key, window, timestamp: now });
    } catch (error) {
      this.emit('error', error);
    }
  }

  processKeystroke(key, window, bufferData, timeSinceLastKey) {
    if (timeSinceLastKey > this.keyDebounceTime && bufferData.buffer.trim().length > 0) {
      this.sendTextBuffer(window, bufferData.buffer);
      bufferData.buffer = '';
    }

    switch (key) {
      case '\\n':
        bufferData.buffer += '\n';
        this.sendTextBuffer(window, bufferData.buffer);
        bufferData.buffer = '';
        break;
      case '\\t':
        bufferData.buffer += '\t';
        break;
      case '\\b':
        if (bufferData.buffer.length > 0) {
          bufferData.buffer = bufferData.buffer.slice(0, -1);
        }
        break;
      default:
        bufferData.buffer += key;
        if (key === '.' || key === '?' || key === '!') {
          const snapshot = bufferData.buffer;
          setTimeout(() => {
            const latest = this.windowBuffers.get(window);
            if (latest && latest.buffer === snapshot) {
              this.sendTextBuffer(window, latest.buffer);
              latest.buffer = '';
            }
          }, 300);
        }
        break;
    }
  }

  sendTextBuffer(window, text) {
    if (!text || text.trim().length === 0) {
      return;
    }

    const cleanText = text.trim();
    const wordCount = cleanText
      .split(/\s+/)
      .filter((word) => word.length > 0)
      .length;

    this.emit('text', {
      text: cleanText,
      timestamp: new Date().toISOString(),
      window,
      charCount: cleanText.length,
      wordCount,
    });
  }

  checkBuffers() {
    const now = Date.now();

    this.windowBuffers.forEach((data, window) => {
      const timeSinceLastKey = now - data.lastKeyTime;
      if (data.buffer.trim().length > 0 && timeSinceLastKey > this.keyDebounceTime) {
        this.sendTextBuffer(window, data.buffer);
        data.buffer = '';
      }
    });
  }
}

module.exports = new KeyLogger();
