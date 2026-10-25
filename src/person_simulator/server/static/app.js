"use strict";

const statusBox = document.getElementById("status");
const messagesBox = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("message");
const sendButton = document.getElementById("send");
const endButton = document.getElementById("end-session");

function setStatus(text) {
  statusBox.textContent = text;
}

function addMessage(role, text) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  const label = document.createElement("span");
  label.className = "label";
  label.textContent = role === "user" ? "你" : "模拟";
  const body = document.createElement("p");
  body.textContent = text;
  node.append(label, body);
  messagesBox.append(node);
  node.scrollIntoView({ block: "end" });
}

async function loadSession() {
  const response = await fetch("/api/session", { credentials: "same-origin" });
  if (!response.ok) {
    setStatus("没有有效邀请，请让所有者重新发送访问链接。");
    sendButton.disabled = true;
    return false;
  }
  const data = await response.json();
  setStatus(`会话 ${data.id.slice(0, 8)} · 已进行 ${data.turns} 轮`);
  return true;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  addMessage("user", text);
  input.value = "";
  sendButton.disabled = true;
  setStatus("正在生成回复…");
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    const data = await response.json();
    if (!response.ok) {
      setStatus(data.message || "请求失败，请稍后重试。");
      return;
    }
    addMessage("assistant", data.reply);
    if (data.notices && data.notices.length) {
      setStatus(data.notices.join(" · "));
    } else {
      setStatus(`已进行 ${data.turn} 轮`);
    }
  } catch (_error) {
    setStatus("网络错误，请稍后重试。");
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
});

endButton.addEventListener("click", async () => {
  await fetch("/api/session/end", {
    method: "POST",
    credentials: "same-origin",
  });
  messagesBox.replaceChildren();
  setStatus("会话已结束。");
  sendButton.disabled = true;
});

loadSession().catch(() => setStatus("无法连接模拟服务。"));
