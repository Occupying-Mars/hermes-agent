console.log = (...args) => process.stderr.write(`${args.join(" ")}\n`);
console.error = (...args) => process.stderr.write(`${args.join(" ")}\n`);

function send(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

let keylogger;
try {
  keylogger = require('./autoclys_keylogger');
} catch (error) {
  send({
    type: 'error',
    data: {
      message: error && error.message ? error.message : String(error),
    },
  });
  process.exit(1);
}

function shutdown() {
  try {
    keylogger.stop();
  } catch (error) {
    send({ type: 'error', data: { message: error.message || String(error) } });
  }
  process.exit(0);
}

keylogger.on('start', () => send({ type: 'status', data: { started: true } }));
keylogger.on('stop', () => send({ type: 'status', data: { started: false } }));
keylogger.on('keystroke', (data) => send({ type: 'keystroke', data }));
keylogger.on('text', (data) => send({ type: 'text', data }));
keylogger.on('error', (error) => send({ type: 'error', data: { message: error.message || String(error) } }));

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
process.on('exit', () => {
  try {
    keylogger.stop();
  } catch (_) {}
});

const started = keylogger.start();
send({ type: 'ready', data: { started } });
if (!started) {
  process.exitCode = 1;
}
