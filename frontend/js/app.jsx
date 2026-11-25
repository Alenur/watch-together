import {useCallback, useEffect, useRef, useState} from 'react';
import {Link, matchPath, useLocation, useNavigate} from 'react-router-dom';
import {api} from './api.js';
import {Room} from './room.jsx';
import {isPlainNavigation, Message} from './ui.jsx';

const roomIdPattern = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;

export function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const candidate = matchPath('/room/:roomId', location.pathname)?.params.roomId;
  const roomId = roomIdPattern.test(candidate ?? '') ? candidate : null;
  const roomControls = useRef(null);
  const [user, setUser] = useState(undefined);
  const [notice, setNotice] = useState('');
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    let active = true;
    api('/auth/me').then((account) => {
      if (active) setUser(account);
    }).catch((error) => {
      if (!active) return;
      setUser(null);
      if (error.status !== 401) setNotice(error.message);
    });
    return () => { active = false; };
  }, []);

  const requireLogin = useCallback(() => {
    setUser(null);
    setNotice('Войдите снова, чтобы продолжить.');
  }, []);

  const leaveRoom = useCallback((message) => {
    navigate('/', {replace: true, state: {notice: message}});
    setNotice('');
  }, [navigate]);

  async function logout(roomNotice = '') {
    setSigningOut(true);
    try {
      await api('/auth/logout', 'POST');
      setUser(null);
      leaveRoom(roomNotice);
    } catch (error) {
      if (roomNotice) leaveRoom(`${roomNotice} ${error.message}`);
      else setNotice(error.message);
    } finally {
      setSigningOut(false);
    }
  }

  function authenticated(account) {
    setUser(account);
    setNotice('');
    if (location.state?.notice) navigate(`${location.pathname}${location.search}${location.hash}`, {replace: true});
  }

  function goHome(event) {
    if (!isPlainNavigation(event)) return;
    if (roomControls.current?.requestClose()) event.preventDefault();
    else setNotice('');
  }

  return <>
    <header className="site-header">
      <div className="header-inner">
        <Link className="brand" to="/" id="brand" onClick={goHome}><span className="brand-mark" aria-hidden="true" />Вместе<span className="brand-period">.</span></Link>
        <div className="profile" id="profile" hidden={!user}>
          <span className="avatar" id="profile-initial" aria-hidden="true">{user?.username[0]}</span>
          <span id="profile-name">{user?.username}</span>
          <button className="button quiet" id="logout" type="button" disabled={signingOut} onClick={() => {
            if (!roomControls.current?.requestClose(true)) void logout();
          }}>Выйти</button>
        </div>
      </div>
    </header>
    <main className="shell">
      <Message className="notice" id="global-notice" role="status">{notice || location.state?.notice}</Message>
      {user === undefined && <p className="loading" id="initial-loading" role="status">Загружаем приложение…</p>}
      {user === null && <Auth invited={Boolean(roomId)} onAuthenticated={authenticated} />}
      {user && !roomId && <Lobby user={user} onAuth={requireLogin} />}
      {user && roomId && <Room key={roomId} ref={roomControls} roomId={roomId} user={user}
        onExit={leaveRoom} onAuth={requireLogin} onLogout={logout} />}
    </main>
  </>;
}

function Auth({invited, onAuthenticated}) {
  const [register, setRegister] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const description = invited ? 'Войдите или зарегистрируйтесь, чтобы открыть приглашение.'
    : register ? 'Создайте аккаунт для совместного просмотра.' : 'Войдите, чтобы открыть свои комнаты.';

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError('');
    try {
      const account = await api(`/auth/${register ? 'register' : 'login'}`, 'POST', {
        username: form.get('username').trim(), password: form.get('password'),
      });
      onAuthenticated(account);
    } catch (error) {
      setError(error.message);
    } finally {
      setBusy(false);
    }
  }

  return <section className="auth-layout" id="auth-view" aria-labelledby="auth-title">
    <div className="auth-intro">
      <div className="screen-art" aria-hidden="true"><div className="art-frame"><div className="art-play" /></div></div>
      <h1>Смотрите <em>вместе</em></h1>
      <p>Откройте видео YouTube в общей комнате, пригласите друзей и обсуждайте просмотр в чате.</p>
    </div>
    <div className="surface auth-card">
      <h2 id="auth-title">{register ? 'Регистрация' : 'Вход'}</h2>
      <p className="muted" id="auth-description">{description}</p>
      <form id="auth-form" className="form-stack" onSubmit={submit}>
        <label htmlFor="username">Имя пользователя</label>
        <input id="username" name="username" autoComplete="username" placeholder="Например, alex" pattern="[A-Za-z0-9_]{3,24}" required />
        <label htmlFor="password">Пароль</label>
        <input id="password" name="password" type="password" placeholder="От 8 символов"
          autoComplete={register ? 'new-password' : 'current-password'} minLength={8} maxLength={128} required />
        <Message className="error" id="auth-error" role="alert">{error}</Message>
        <button className="button primary" id="auth-submit" disabled={busy}>{register ? 'Создать аккаунт' : 'Войти'}</button>
      </form>
      <div className="auth-switch"><span id="auth-switch-label">{register ? 'Уже есть аккаунт?' : 'Впервые здесь?'}</span>{' '}
        <button className="text-button" type="button" id="auth-switch" onClick={() => {
          setRegister(!register);
          setError('');
        }}>{register ? 'Войти' : 'Зарегистрироваться'}</button>
      </div>
    </div>
  </section>;
}

function Lobby({user, onAuth}) {
  const navigate = useNavigate();
  const [rooms, setRooms] = useState(null);
  const [listError, setListError] = useState('');
  const [createError, setCreateError] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let active = true;
    api('/rooms').then((list) => {
      if (active) setRooms(list);
    }).catch((error) => {
      if (!active) return;
      if (error.status === 401) onAuth();
      else setListError(error.message);
    });
    return () => { active = false; };
  }, [onAuth]);

  async function create(event) {
    event.preventDefault();
    if (creating) return;
    const name = new FormData(event.currentTarget).get('name').trim();
    setCreating(true);
    setCreateError('');
    try {
      const room = await api('/rooms', 'POST', {name});
      navigate(`/room/${room.id}`);
    } catch (error) {
      if (error.status === 401) onAuth();
      else setCreateError(error.message);
    } finally {
      setCreating(false);
    }
  }

  return <section id="lobby-view" aria-labelledby="lobby-title">
    <div className="page-heading"><div><h1 id="lobby-title">Мои комнаты</h1><p className="muted">Создайте комнату или вернитесь к просмотру.</p></div></div>
    <div className="lobby-layout">
      <div className="surface create-card">
        <h2>Новая комната</h2>
        <form id="create-form" className="form-stack" onSubmit={create}>
          <label htmlFor="room-name">Название</label>
          <input id="room-name" name="name" placeholder="Например, вечер кино" minLength={2} maxLength={80} required />
          <Message className="error" id="create-error" role="alert">{createError}</Message>
          <button className="button primary" disabled={creating}>Создать комнату</button>
        </form>
      </div>
      <div className="room-list" id="room-list" aria-label="Список моих комнат">
        {listError || (rooms === null ? 'Загружаем комнаты…' : rooms.length === 0
          ? <p className="surface muted empty-lobby">У вас пока нет комнат.</p>
          : rooms.map((room) => <Link className="surface room-link" to={`/room/${room.id}`} key={room.id}>
            <div><strong>{room.name}</strong><small>{room.owner_id === user.id ? 'Организатор' : 'Участник'}</small></div>
            <span aria-hidden="true">→</span>
          </Link>))}
      </div>
    </div>
  </section>;
}
