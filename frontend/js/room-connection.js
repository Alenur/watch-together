import {useEffect, useRef, useState} from 'react';
import {YouTubeSync} from './player.js';

export function useRoomConnection(room, playerMount, closing, onExit, onAuth) {
  const connection = useRef(null);
  const [playback, setPlayback] = useState(room.playback);
  const [live, setLive] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [status, setStatus] = useState('Подключаемся…');
  const [members, setMembers] = useState([]);
  const [history, setHistory] = useState({messages: [], snapshot: 0});
  const [chatError, setChatError] = useState('');
  const [playerNotice, setPlayerNotice] = useState('');

  useEffect(() => {
    let socket;
    let pingTimer;
    let retry;
    let attempt = 0;
    let ready = false;
    let active = true;
    let revision = room.playback.revision;

    function send(event) {
      if (!ready || socket?.readyState !== WebSocket.OPEN) return false;
      socket.send(JSON.stringify(event));
      return true;
    }

    function ping() {
      send({type: 'ping', sent_at: Date.now()});
    }

    const player = new YouTubeSync(playerMount.current, send, setPlayerNotice, () => socket?.close());
    player.setState(room.playback);

    function acceptPlayback(state, acknowledgment) {
      if (acknowledgment) player.acknowledge(acknowledgment);
      if (state.revision < revision) return;
      revision = state.revision;
      if (!acknowledgment) player.setState(state);
      setPlayback(state);
    }

    function receive(event) {
      switch (event.type) {
        case 'snapshot':
          attempt = 0;
          player.clockOffset = Date.parse(event.server_time) - Date.now();
          acceptPlayback(event.room.playback);
          setMembers(event.members);
          setHistory(({snapshot}) => ({messages: event.messages, snapshot: snapshot + 1}));
          ready = true;
          player.setConnected(true);
          setAccepted(true);
          setLive(true);
          setStatus('Комната подключена');
          ping();
          clearInterval(pingTimer);
          pingTimer = setInterval(ping, 15000);
          break;
        case 'playback':
          acceptPlayback(event.playback);
          break;
        case 'player_ack':
          acceptPlayback(event.playback, event);
          break;
        case 'chat':
          setHistory((current) => event.message.id > (current.messages.at(-1)?.id ?? 0)
            ? {...current, messages: [...current.messages.slice(-299), event.message]} : current);
          break;
        case 'member_joined':
          setMembers((current) => [...current.filter(({id}) => id !== event.user.id), event.user]);
          break;
        case 'member_removed':
          setMembers((current) => current.filter(({id}) => id !== event.user_id));
          break;
        case 'pong': {
          const now = Date.now();
          if (now - event.sent_at < 2000) player.clockOffset = Date.parse(event.server_time) - (event.sent_at + now) / 2;
          break;
        }
        case 'error':
          setChatError(event.detail);
          break;
      }
    }

    function connect() {
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${protocol}//${location.host}/ws/rooms/${room.id}`);
      socket = ws;
      ws.addEventListener('message', (event) => {
        if (active && socket === ws) receive(JSON.parse(event.data));
      });
      ws.addEventListener('close', ({code}) => {
        if (!active || socket !== ws) return;
        clearInterval(pingTimer);
        ready = false;
        player.setConnected(false);
        setLive(false);
        if (code === 4403) onExit('Организатор исключил вас из комнаты.');
        else if (code === 4401) onAuth();
        else if (code === 4404 || code === 4410) {
          if (!closing.current) onExit('Комната закрыта.');
        } else {
          setStatus('Переподключаемся…');
          retry = setTimeout(connect, Math.min(1000 * 2 ** attempt, 10000));
          attempt++;
        }
      });
    }

    function onVisibility() {
      if (!document.hidden) ping();
    }

    connection.current = {send, acceptPlayback};
    document.addEventListener('visibilitychange', onVisibility);
    connect();
    return () => {
      active = false;
      connection.current = null;
      document.removeEventListener('visibilitychange', onVisibility);
      clearInterval(pingTimer);
      clearTimeout(retry);
      socket?.close();
      player.destroy();
    };
  }, [room, playerMount, closing, onExit, onAuth]);

  return {connection, playback, live, accepted, status, members, history, chatError, setChatError, playerNotice};
}
