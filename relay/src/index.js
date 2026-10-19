// Cards Against Humanity relay: a dumb WebSocket switchboard, one Durable Object per room code.
// Like Epic's relay for Baldi's multiplayer, it lets players on networks that block
// device-to-device traffic (school Wi-Fi, different houses) reach the host. Game logic
// stays on the host's PC; this only forwards messages.
//
//   wss://<worker>/room/<CODE>?role=host     the hosting game (one per room)
//   wss://<worker>/room/<CODE>?role=client   players joining with the code
//
// Host -> relay: {"t":"to","cid":N,"m":<obj>} | {"t":"all","m":<obj>} | {"t":"kick","cid":N,"reason":"..."}
// Relay -> host: {"t":"join","cid":N} | {"t":"from","cid":N,"m":"<raw text>"} | {"t":"leave","cid":N}
// Clients send and receive the game's own JSON messages untouched.
// Text "ping" is answered with "pong" without waking the object (keeps school proxies from idling us out).
import { DurableObject } from "cloudflare:workers";

const OPEN = 1;
const REPO = "JumpYbutSchooled/Cards-against-humanity-LAN";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/" || url.pathname === "/health") {
      return new Response("cah-relay ok", { headers: { "content-type": "text/plain" } });
    }
    // Update mirror: if a school filter blocks GitHub's download hosts, the game's updater
    // can still fetch the newest version through here (we already know this host gets through).
    if (url.pathname === "/update/VERSION" || url.pathname === "/update/zip") {
      const zip = url.pathname.endsWith("zip");
      const upstream = zip
        ? `https://codeload.github.com/${REPO}/zip/refs/heads/main`
        : `https://api.github.com/repos/${REPO}/contents/VERSION?ref=main`;
      const r = await fetch(upstream, {
        headers: { "User-Agent": "cah-relay-mirror", Accept: zip ? "*/*" : "application/vnd.github.raw" },
      });
      if (!r.ok) return new Response(`upstream ${r.status}`, { status: 502 });
      return new Response(r.body, {
        headers: { "content-type": zip ? "application/zip" : "text/plain", "cache-control": "no-store" },
      });
    }
    const m = url.pathname.match(/^\/room\/([A-Za-z0-9]{4,8})$/);
    if (!m) return new Response("not found", { status: 404 });
    if (request.headers.get("Upgrade") !== "websocket") {
      return new Response("expected a websocket", { status: 426 });
    }
    const code = m[1].toUpperCase();
    return env.ROOMS.get(env.ROOMS.idFromName(code)).fetch(request);
  },
};

export class Room extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair("ping", "pong"));
  }

  host() {
    return this.ctx.getWebSockets("host").find((w) => w.readyState === OPEN);
  }

  client(cid) {
    return this.ctx.getWebSockets("c" + cid).find((w) => w.readyState === OPEN);
  }

  reject(code, reason) {
    const [client, server] = Object.values(new WebSocketPair());
    server.accept();
    server.close(code, reason);
    return new Response(null, { status: 101, webSocket: client });
  }

  async fetch(request) {
    const role = new URL(request.url).searchParams.get("role");
    if (role === "host") {
      if (this.host()) return this.reject(4009, "Room code already in use");
      const [client, server] = Object.values(new WebSocketPair());
      this.ctx.acceptWebSocket(server, ["host"]);
      return new Response(null, { status: 101, webSocket: client });
    }
    const host = this.host();
    if (!host) return this.reject(4004, "No game with that code");
    if (this.ctx.getWebSockets("client").length >= 16) return this.reject(4005, "That game is full");
    const cid = ((await this.ctx.storage.get("n")) || 0) + 1;
    await this.ctx.storage.put("n", cid);
    const [client, server] = Object.values(new WebSocketPair());
    this.ctx.acceptWebSocket(server, ["client", "c" + cid]);
    server.serializeAttachment({ cid });
    host.send(JSON.stringify({ t: "join", cid }));
    return new Response(null, { status: 101, webSocket: client });
  }

  async webSocketMessage(ws, message) {
    if (typeof message !== "string") return;
    const tags = this.ctx.getTags(ws);
    if (tags.includes("host")) {
      let d;
      try {
        d = JSON.parse(message);
      } catch {
        return;
      }
      if (d.t === "to") {
        const c = this.client(d.cid);
        if (c) safeSend(c, JSON.stringify(d.m));
      } else if (d.t === "all") {
        const text = JSON.stringify(d.m);
        for (const c of this.ctx.getWebSockets("client")) safeSend(c, text);
      } else if (d.t === "kick") {
        const c = this.client(d.cid);
        if (c) c.close(4003, String(d.reason || "Removed by the host").slice(0, 100));
      }
      return;
    }
    const { cid } = ws.deserializeAttachment() || {};
    const host = this.host();
    if (host && cid != null) safeSend(host, JSON.stringify({ t: "from", cid, m: message }));
  }

  async webSocketClose(ws, code, reason) {
    this.gone(ws);
    try {
      ws.close(1000, "bye");
    } catch {}
  }

  async webSocketError(ws) {
    this.gone(ws);
  }

  gone(ws) {
    const tags = this.ctx.getTags(ws);
    if (tags.includes("host")) {
      if (this.host()) return; // a newer host connection already took over
      for (const c of this.ctx.getWebSockets("client")) {
        try {
          c.close(4001, "Host disconnected");
        } catch {}
      }
    } else if (tags.includes("client")) {
      const { cid } = ws.deserializeAttachment() || {};
      const host = this.host();
      if (host && cid != null) safeSend(host, JSON.stringify({ t: "leave", cid }));
    }
  }
}

function safeSend(ws, text) {
  try {
    ws.send(text);
  } catch {}
}
