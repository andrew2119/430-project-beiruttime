// Screenshot-only loopback adapter: supplies the existing SSR theme cookie.
// It does not rewrite HTML/CSS/JS or bypass the app's BFF/auth behavior.
import { createServer, request } from 'node:http';
for (const [port, theme, destination, cookie] of [[3354, 'light', 3357, 'bt-theme'], [3355, 'dark', 3357, 'bt-theme'], [3352, 'light', 3356, 'bt-theme'], [3353, 'dark', 3356, 'bt-theme']]) {
  createServer((incoming, outgoing) => {
    const headers = { ...incoming.headers, cookie: `${cookie}=${theme}; ${incoming.headers.cookie ?? ''}` };
    const upstream = request({ hostname: '127.0.0.1', port: destination, path: incoming.url, method: incoming.method, headers }, response => {
      outgoing.writeHead(response.statusCode, response.headers);
      response.pipe(outgoing);
    });
    upstream.on('error', () => { outgoing.statusCode = 503; outgoing.end('Proof app is not ready'); });
    incoming.pipe(upstream);
  }).listen(port, '127.0.0.1', () => console.log(`${theme} screenshots: http://127.0.0.1:${port}`));
}
