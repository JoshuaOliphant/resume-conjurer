import { App } from '@modelcontextprotocol/ext-apps';
import { mountPanel } from './panel.js';

const app = new App({ name: 'Conjurer synthetic curation', version: '0.1.0' }, {});
let bridgeReady;
const panel = mountPanel(document.getElementById('app'), async args => {
  await bridgeReady;
  return app.callServerTool(args);
});
app.ontoolresult = result => panel.receive(result);
app.ontoolcancelled = () => panel.cancelled();
app.onclose = () => panel.disconnected();
app.onteardown = async () => { panel.disconnected(); return {}; };
try {
  bridgeReady = app.connect();
  await bridgeReady;
  await panel.refresh({ automatic: true });
} catch {
  panel.disconnected();
}
