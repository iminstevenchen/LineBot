const response = await fetch(
  "https://vatican-westminster-author-april.trycloudflare.com/api/chat",
  {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: "你好" }),
  }
);
const data = await response.json();
console.log(data.answer);
