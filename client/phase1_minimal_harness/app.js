const joinBtn = document.getElementById("join-btn");
const statusDiv = document.getElementById("status");
const logPanel = document.getElementById("log-panel");
const audioEl = document.getElementById("agent-audio");

let room;

async function fetchToken(sessionId, roomName) {
  // Call edge-auth API gateway route on port 8003
  const response = await fetch("http://localhost:8003/auth", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      session_id: sessionId,
      room_name: roomName
    })
  });
  if (!response.ok) {
    throw new Error("Failed to retrieve token from API Gateway");
  }
  const data = await response.json();
  return data.token;
}

async function connectToRoom(token) {
  // Retrieve LiveKit SDK class from global window scope
  const { Room, RoomEvent } = LiveKitClient;
  
  room = new Room();
  
  // Set event listeners for subscribed tracks
  room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
    if (track.kind === "audio") {
      track.attach(audioEl);
      renderLogEvent({ event: "track_subscribed", detail: { track_kind: "audio", identity: participant.identity } });
    }
  });

  room.on(RoomEvent.ParticipantConnected, (participant) => {
    renderLogEvent({ event: "participant_connected", detail: { identity: participant.identity } });
  });

  statusDiv.textContent = "Connecting...";
  
  // Connect using token. The LiveKit URL is fetched by room manager backend
  // but client connects using standard LiveKit WS endpoint configured in token metadata/URL
  const livekitUrl = "ws://localhost:7800"; // standard local LiveKit URL fallback
  await room.connect(livekitUrl, token);
  
  statusDiv.textContent = "Connected to Room";
  renderLogEvent({ event: "room_joined", detail: { room: room.name } });

  // Publish microphone track
  await room.localParticipant.setMicrophoneEnabled(true);
  renderLogEvent({ event: "track_published", detail: { track_kind: "audio" } });
}

function renderLogEvent(logData) {
  const entry = document.createElement("div");
  entry.className = "log-entry";
  entry.textContent = `[${new Date().toLocaleTimeString()}] ${logData.event}: ${JSON.stringify(logData.detail || {})}`;
  logPanel.appendChild(entry);
  logPanel.scrollTop = logPanel.scrollHeight;
}

joinBtn.addEventListener("click", async () => {
  const sessionId = "session-" + Math.random().toString(36).substring(2, 9);
  const roomName = "demo-room";
  
  try {
    const token = await fetchToken(sessionId, roomName);
    await connectToRoom(token);
  } catch (err) {
    renderLogEvent({ event: "error", detail: { message: err.message } });
    statusDiv.textContent = "Connection Failed";
  }
});
