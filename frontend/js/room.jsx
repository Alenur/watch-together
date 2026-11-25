import {useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {Link} from 'react-router-dom';
import {api} from './api.js';
import {useRoomConnection} from './room-connection.js';
import {isPlainNavigation, Message} from './ui.jsx';

const timeFormat = new Intl.DateTimeFormat('ru', {hour: '2-digit', minute: '2-digit'});

export function Room({roomId, user, onExit, onAuth, onLogout, ref}) {
  const [room, setRoom] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    api(`/rooms/${roomId}/join`, 'POST').then((data) => {
      if (active) setRoom(data);
    }).catch((error) => {
      if (!active) return;
      if (error.status === 401) onAuth();
      else setError(error.message);
    });
    return () => { active = false; };
  }, [roomId, onAuth]);

  if (!room) return <section id="room-view" aria-labelledby="room-title">
    <RoomHeading status={error ? 'Доступ к комнате закрыт' : 'Открываем комнату…'} state={error ? 'closed' : 'waiting'} />
    <Message className="error notice" id="room-error" role="alert">{error}</Message>
  </section>;

  return <ActiveRoom room={room} user={user} onExit={onExit} onAuth={onAuth} onLogout={onLogout} ref={ref} />;
}

function RoomHeading({name = 'Комната', status, state, onBack, children}) {
  return <div className="page-heading room-heading">
    <div>
      <Link className="back-link" to="/" id="back-link" onClick={onBack}>← Мои комнаты</Link>
      <h1 id="room-title">{name}</h1>
      <p className="connection" id="connection" data-state={state} role="status">{status}</p>
    </div>
    <div className="room-actions">{children}</div>
  </div>;
}

function ActiveRoom({room, user, onExit, onAuth, onLogout, ref}) {
  const playerMount = useRef(null);
  const closing = useRef(false);
  const closeDialog = useRef(null);
  const logoutAfterClose = useRef(false);
  const inviteInput = useRef(null);
  const copyTimer = useRef(null);
  const isOwner = room.owner_id === user.id;
  const inviteUrl = new URL(`/room/${room.id}`, location.origin).href;
  const [roomError, setRoomError] = useState('');
  const [videoError, setVideoError] = useState('');
  const [savingVideo, setSavingVideo] = useState(false);
  const [closePending, setClosePending] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showInvite, setShowInvite] = useState(false);
  const {connection, playback, live, accepted, status, members, history, chatError, setChatError, playerNotice} =
    useRoomConnection(room, playerMount, closing, onExit, onAuth);
  const hasVideo = Boolean(playback.video_id);

  const requestClose = useCallback((logout = false) => {
    if (!isOwner) return false;
    const dialog = closeDialog.current;
    if (!closing.current && dialog && !dialog.open) {
      logoutAfterClose.current = logout;
      dialog.returnValue = '';
      dialog.showModal();
    }
    return true;
  }, [isOwner]);

  useImperativeHandle(ref, () => ({requestClose}), [requestClose]);
  useEffect(() => () => clearTimeout(copyTimer.current), []);

  async function closeRoom(event) {
    if (event.currentTarget.returnValue !== 'close' || closing.current) return;
    closing.current = true;
    setClosePending(true);
    setRoomError('');
    try {
      await api(`/rooms/${room.id}`, 'DELETE');
    } catch (error) {
      if (!connection.current) return;
      if (error.status === 401) return onAuth();
      if (error.status !== 404) {
        closing.current = false;
        setClosePending(false);
        setRoomError(error.message);
        return;
      }
    }
    if (!connection.current) return;
    if (logoutAfterClose.current) void onLogout('Комната закрыта.');
    else onExit('Комната закрыта.');
  }

  async function saveVideo(event) {
    event.preventDefault();
    if (!live || savingVideo) return;
    const form = event.currentTarget;
    const url = new FormData(form).get('url').trim();
    setSavingVideo(true);
    setVideoError('');
    try {
      const state = await api(`/rooms/${room.id}/video`, 'PUT', {url});
      if (!connection.current) return;
      form.reset();
      connection.current.acceptPlayback(state);
    } catch (error) {
      if (!connection.current) return;
      if (error.status === 401) onAuth();
      else setVideoError(error.message);
    } finally {
      if (connection.current) setSavingVideo(false);
    }
  }

  async function copyInvite() {
    try {
      await navigator.clipboard.writeText(inviteUrl);
      if (!connection.current) return;
      setCopied(true);
      clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      if (!connection.current) return;
      if (showInvite) focusInvite();
      else setShowInvite(true);
    }
  }

  const focusInvite = useCallback(() => {
    inviteInput.current.focus();
    inviteInput.current.select();
  }, []);
  useLayoutEffect(() => {
    if (showInvite) focusInvite();
  }, [focusInvite, showInvite]);

  return <>
    <section id="room-view" aria-labelledby="room-title">
      <RoomHeading name={room.name} status={status}
        state={live ? 'live' : 'waiting'} onBack={(event) => {
          if (isPlainNavigation(event) && requestClose()) event.preventDefault();
        }}>
        <button className="button secondary" id="invite" type="button" hidden={!hasVideo || !accepted} onClick={copyInvite}>
          {copied ? 'Ссылка скопирована' : 'Скопировать приглашение'}
        </button>
        <button className="button danger" id="close-room" type="button" hidden={!isOwner} disabled={closePending}
          onClick={() => requestClose()}>Закрыть комнату</button>
      </RoomHeading>
      <div className="surface invite-fallback" id="invite-fallback" hidden={!showInvite}>
        <label htmlFor="invite-url">Ссылка-приглашение</label>
        <input id="invite-url" readOnly ref={inviteInput} value={showInvite ? inviteUrl : ''} onClick={focusInvite} />
      </div>
      <Message className="error notice" id="room-error" role="alert">{roomError}</Message>
      <div className="watch-grid" id="room-content">
        <div className="watch-column">
          <div className="surface video-card">
            <div className="stage" id="stage">
              <div id="player-mount" className="player-mount" hidden={!hasVideo} ref={playerMount} />
              <div className="stage-empty" id="stage-empty" hidden={hasVideo}>
                <span className="stage-icon" aria-hidden="true"><i /></span>
                <strong>Видео ещё не добавлено</strong>
                <span id="stage-help">{isOwner ? 'Добавьте ссылку на YouTube, чтобы начать просмотр.' : 'Организатор добавит ссылку на YouTube.'}</span>
              </div>
            </div>
            <Message className="player-notice" id="player-notice" role="status">{playerNotice}</Message>
          </div>
          <form className="surface video-form" id="video-form" hidden={!isOwner} onSubmit={saveVideo}>
            <label htmlFor="video-link">Ссылка на YouTube</label>
            <div className="input-row">
              <input id="video-link" name="url" type="url" placeholder="https://www.youtube.com/watch?v=…" maxLength={2048} required />
              <button className="button primary" id="video-submit" disabled={!live || savingVideo}>{hasVideo ? 'Заменить видео' : 'Добавить видео'}</button>
            </div>
            <Message className="error" id="video-error" role="alert">{videoError}</Message>
          </form>
        </div>
        <RoomPanel room={room} user={user} isOwner={isOwner} live={live} connection={connection} members={members}
          history={history} chatError={chatError} setChatError={setChatError} onAuth={onAuth} />
      </div>
    </section>
    {createPortal(<dialog id="close-dialog" className="surface dialog" aria-labelledby="close-dialog-title" ref={closeDialog} onClose={closeRoom}>
      <form method="dialog">
        <h2 id="close-dialog-title">Закрыть комнату?</h2>
        <p className="muted">Участники вернутся к списку комнат. Комната и история чата будут удалены.</p>
        <div className="dialog-actions">
          <button className="button secondary" value="cancel" autoFocus>Отмена</button>
          <button className="button danger" value="close">Закрыть комнату</button>
        </div>
      </form>
    </dialog>, document.body)}
  </>;
}

function RoomPanel({room, user, isOwner, live, connection, members, history, chatError, setChatError, onAuth}) {
  const [tab, setTab] = useState('chat');
  const [membersError, setMembersError] = useState('');
  const [kickTarget, setKickTarget] = useState(null);
  const tabs = useRef({});
  const log = useRef(null);
  const following = useRef(true);
  const kickDialog = useRef(null);

  useLayoutEffect(() => {
    following.current = true;
  }, [history.snapshot, tab]);

  useLayoutEffect(() => {
    const latest = history.messages.at(-1);
    if (tab === 'chat' && (following.current || latest?.user.id === user.id)) {
      log.current.scrollTop = log.current.scrollHeight;
    }
  }, [history, tab, user.id]);

  function switchWithKeyboard(event) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 'chat' : event.key === 'End' ? 'members' : tab === 'chat' ? 'members' : 'chat';
    setTab(next);
    tabs.current[next].focus();
  }

  function sendMessage(event) {
    event.preventDefault();
    if (!live) return;
    const form = event.currentTarget;
    const text = new FormData(form).get('message').trim();
    if (text && connection.current?.send({type: 'chat', text})) {
      form.reset();
      setChatError('');
    }
  }

  function askKick(member) {
    const dialog = kickDialog.current;
    if (dialog.open) return;
    setKickTarget(member);
    dialog.returnValue = '';
    dialog.showModal();
  }

  async function confirmKick(event) {
    const target = kickTarget;
    setKickTarget(null);
    if (event.currentTarget.returnValue !== 'kick' || !target) return;
    setMembersError('');
    try {
      await api(`/rooms/${room.id}/members/${target.id}`, 'DELETE');
    } catch (error) {
      if (!connection.current) return;
      if (error.status === 401) onAuth();
      else setMembersError(error.message);
    }
  }

  const orderedMembers = [...members].sort((left, right) => {
    if (left.id === room.owner_id) return -1;
    if (right.id === room.owner_id) return 1;
    return left.username.localeCompare(right.username);
  });

  return <>
    <aside className="surface room-panel" aria-label="Общение в комнате">
      <div className="panel-tabs" role="tablist" aria-label="Общение в комнате">
        {['chat', 'members'].map((key) => <button key={key} type="button" role="tab" id={`${key}-tab`}
          aria-selected={tab === key} aria-controls={`${key}-panel`} tabIndex={tab === key ? 0 : -1}
          ref={(button) => { tabs.current[key] = button; }} onClick={() => setTab(key)} onKeyDown={switchWithKeyboard}>
          {key === 'chat' ? 'Чат' : <>Участники <span className="count" id="member-count">{members.length}</span></>}
        </button>)}
      </div>
      <div className="chat-panel" id="chat-panel" role="tabpanel" aria-labelledby="chat-tab" hidden={tab !== 'chat'}>
        <div className="chat-log" id="chat-log" role="log" aria-label="Сообщения чата" ref={log} onScroll={(event) => {
          const element = event.currentTarget;
          following.current = element.scrollHeight - element.scrollTop - element.clientHeight < 55;
        }}>
          {history.messages.length ? history.messages.map((message) => <article className="chat-message" key={message.id}>
            <span className="avatar" aria-hidden="true">{message.user.username[0]}</span>
            <div>
              <div className="chat-byline"><strong>{message.user.username}</strong>
                <time dateTime={message.created_at}>{timeFormat.format(new Date(message.created_at))}</time></div>
              <p className="message-body">{message.text}</p>
            </div>
          </article>) : <p className="panel-empty">Пока нет сообщений. Начните разговор.</p>}
        </div>
        <Message className="error chat-error" id="chat-error" role="alert">{chatError}</Message>
        <form className="chat-form" id="chat-form" onSubmit={sendMessage}>
          <input name="message" id="message" placeholder="Написать сообщение…" maxLength={500} aria-label="Сообщение" autoComplete="off" required disabled={!live} />
          <button className="button primary send-button" id="send" aria-label="Отправить сообщение" title="Отправить сообщение" disabled={!live}>↑</button>
        </form>
      </div>
      <div className="members-panel" id="members-panel" role="tabpanel" aria-labelledby="members-tab" hidden={tab !== 'members'}>
        <Message className="error" id="members-error" role="alert">{membersError}</Message>
        <ul className="member-list" id="member-list">
          {orderedMembers.map((member) => <li className="member-row" key={member.id}>
            <span className="avatar" aria-hidden="true">{member.username[0]}</span>
            <div><strong>{member.username}{member.id === user.id ? ' (вы)' : ''}</strong>
              {member.id === room.owner_id && <small>Организатор</small>}</div>
            {isOwner && member.id !== user.id && <button className="button quiet" type="button" disabled={!live}
              aria-label={`Исключить ${member.username}`} onClick={() => askKick(member)}>Исключить</button>}
          </li>)}
        </ul>
      </div>
    </aside>
    {createPortal(<dialog id="kick-dialog" className="surface dialog" ref={kickDialog} onClose={confirmKick}>
      <form method="dialog">
        <h2>Исключить участника?</h2>
        <p id="kick-description" className="muted">{kickTarget && `${kickTarget.username} будет отключён и потеряет доступ к этой комнате.`}</p>
        <div className="dialog-actions">
          <button className="button secondary" value="cancel" autoFocus>Отмена</button>
          <button className="button danger" value="kick">Исключить</button>
        </div>
      </form>
    </dialog>, document.body)}
  </>;
}
