"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const checkpoints = [
    { label: "EN ROUTE", lat: 0.416, lng: 9.467, delay: 0 },
    { label: "ARRIVÉ", lat: 0.418, lng: 9.471, delay: 5000 },
    { label: "ENFANT RÉCUPÉRÉ", lat: 0.419, lng: 9.474, delay: 10000 },
    { label: "ENFANT DÉPOSÉ", lat: 0.424, lng: 9.478, delay: 15000 },
    { label: "TERMINÉ", lat: 0.431, lng: 9.482, delay: 20000 }
  ];

  const feed = document.getElementById("checkpoint-feed");
  const notificationFeed = document.getElementById("notification-feed");

  if (!feed) {
    return;
  }

  setInterval(() => {
    const checkpoint = checkpoints[Math.floor(Math.random() * checkpoints.length)];
    const li = document.createElement("li");
    li.className = "list-group-item small text-muted";
    li.textContent = `${checkpoint.label} • ${new Date().toLocaleTimeString()}`;
    feed.prepend(li);
    if (feed.children.length > 5) {
      feed.removeChild(feed.lastElementChild);
    }

    if (notificationFeed) {
      const notif = document.createElement("li");
      notif.className = "list-group-item";
      notif.innerHTML = `<span class="fw-semibold">${checkpoint.label}</span><div class="text-muted">${new Date().toLocaleTimeString()}</div>`;
      notificationFeed.prepend(notif);
      if (notificationFeed.children.length > 5) {
        notificationFeed.removeChild(notificationFeed.lastElementChild);
      }
    }
  }, 7000);
});





