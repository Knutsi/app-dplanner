// node tools/serve.mjs [port] — open the printed address; the theme follows Omarchy's.
import { serve } from "./server.mjs";
const server = await serve(Number(process.argv[2] ?? 8417));
const port = server.address().port;
console.log(`http://localhost:${port}/desktop.html   http://localhost:${port}/mobile.html   http://localhost:${port}/gallery.html`);
