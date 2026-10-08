const box = document.createElement("div");
box.style.cssText = [
  "position:fixed",
  "right:16px",
  "bottom:16px",
  "z-index:2147483647",
  "display:flex",
  "gap:8px",
  "align-items:center",
  "font-family:sans-serif",
].join(";");

function button(label, action, color) {
  const node = document.createElement("button");
  node.textContent = label;
  node.style.cssText = [
    "border:0",
    "border-radius:8px",
    "padding:12px 16px",
    "font-size:16px",
    "font-weight:700",
    "color:#fff",
    `background:${color}`,
    "cursor:pointer",
  ].join(";");
  node.addEventListener("click", () => {
    chrome.runtime.sendMessage({ type: "override", action });
  });
  return node;
}

const mark = document.createElement("img");
mark.src = chrome.runtime.getURL("icon.svg");
mark.alt = "OHush";
mark.style.cssText = "height:36px;width:auto;display:block";

const label = document.createElement("span");
label.style.cssText = "color:#f4eef8;background:#3b1655;padding:8px 10px;border-radius:8px";
label.textContent = "OHush";
box.append(mark, button("PLAY", "play", "#1f7a3a"), button("MUTE", "mute", "#8d2a2a"), label);
document.documentElement.append(box);

setInterval(() => {
  chrome.runtime.sendMessage({ type: "state" }, (body) => {
    if (!body || !body.state) return;
    label.textContent = `${body.state} ${body.replacement || ""}`.trim();
  });
}, 500);
