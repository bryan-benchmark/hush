const DAEMON = "http://127.0.0.1:8770";

async function override(action) {
  const response = await fetch(`${DAEMON}/override`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  return response.json();
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === "state") {
    fetch(`${DAEMON}/state`)
      .then((response) => response.json())
      .then(sendResponse)
      .catch((error) => sendResponse({ error: String(error) }));
    return true;
  }
  if (message.type === "override") {
    override(message.action)
      .then(sendResponse)
      .catch((error) => sendResponse({ error: String(error) }));
    return true;
  }
  return false;
});

chrome.commands.onCommand.addListener((command) => {
  if (command === "mute-now") override("mute");
  if (command === "play-now") override("play");
});
