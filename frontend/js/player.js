let youtubeReady;

function loadYouTube() {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (!youtubeReady) {
    youtubeReady = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      const fail = () => {
        clearTimeout(timeout);
        script.remove();
        youtubeReady = undefined;
        reject(new Error('Не удалось загрузить YouTube.'));
      };
      const timeout = setTimeout(fail, 12000);
      window.onYouTubeIframeAPIReady = () => {
        clearTimeout(timeout);
        resolve(window.YT);
      };
      script.src = 'https://www.youtube.com/iframe_api';
      script.onerror = fail;
      document.head.append(script);
    });
  }
  return youtubeReady;
}

const ENDED = 0;
const PLAYING = 1;
const PAUSED = 2;
const BUFFERING = 3;
const CUED = 5;
const MAX_POSITION = 172800;

export class YouTubeSync {
  constructor(mount, send, onNotice, onTimeout) {
    this.mount = mount;
    this.send = send;
    this.onNotice = onNotice;
    this.onTimeout = onTimeout;
    this.generation = 0;
    this.sequence = 0;
    this.clockOffset = 0;
    this.interval = setInterval(() => this.observe(), 200);
  }

  setConnected(connected) {
    if (this.connected === connected) return;
    this.connected = connected;
    this.clearIntents();
    this.sample = undefined;
    if (connected) this.startCorrection();
    else this.correction = undefined;
  }

  setState(state) {
    if (this.state && state.revision <= this.state.revision) return;
    const old = this.state;
    this.state = state;
    if (state.video_id !== old?.video_id) {
      this.unload();
      if (state.video_id) void this.load(state.video_id, this.generation);
    } else if (!this.pending && !this.queued) {
      this.startCorrection();
    }
  }

  async load(videoId, generation) {
    this.onNotice('Загружаем плеер YouTube…');
    try {
      const yt = await loadYouTube();
      if (this.generation !== generation) return;
      const iframe = document.createElement('iframe');
      const params = new URLSearchParams({enablejsapi: '1', origin: location.origin, playsinline: '1'});
      iframe.src = `https://www.youtube.com/embed/${videoId}?${params}`;
      iframe.title = 'Плеер YouTube';
      iframe.allow = 'autoplay; encrypted-media; fullscreen; picture-in-picture';
      iframe.allowFullscreen = true;
      iframe.referrerPolicy = 'strict-origin-when-cross-origin';
      this.mount.replaceChildren(iframe);
      this.loadTimeout = setTimeout(() => {
        if (this.generation === generation && !this.ready) {
          this.onNotice('YouTube не ответил. Проверьте соединение и обновите страницу.');
        }
      }, 15000);
      this.player = new yt.Player(iframe, {
        events: {
          onReady: () => {
            if (this.generation !== generation || this.failed) return;
            clearTimeout(this.loadTimeout);
            this.ready = true;
            this.onNotice('');
            this.startCorrection();
          },
          onAutoplayBlocked: () => {
            if (this.generation === generation && this.state.playing && this.correction) {
              this.blocked = true;
              this.correction = undefined;
              this.onNotice('Нажмите воспроизведение в плеере, чтобы подключиться к просмотру.');
            }
          },
          onError: ({data}) => {
            if (this.generation !== generation) return;
            clearTimeout(this.loadTimeout);
            this.ready = false;
            this.failed = true;
            this.onNotice(data === 101 || data === 150
              ? 'Автор видео запретил встраивание. Добавьте другое видео.'
              : 'YouTube не смог воспроизвести это видео. Проверьте ссылку или попробуйте другую.');
          },
        },
      });
    } catch {
      if (this.generation === generation) this.onNotice('Не удалось подключиться к YouTube. Обновите страницу, чтобы повторить.');
    }
  }

  roomPosition() {
    const elapsed = this.state.playing
      ? Math.max(0, (Date.now() + this.clockOffset - Date.parse(this.state.updated_at)) / 1000) : 0;
    return Math.min(this.player.getDuration() || MAX_POSITION, this.state.position + elapsed * this.state.rate);
  }

  readPlayer() {
    const status = this.player.getPlayerState();
    const duration = this.player.getDuration();
    const current = this.player.getCurrentTime() || 0;
    const position = status === CUED || status === -1 ? this.cuedAt : current;
    return {status, duration, position, playing: status === PLAYING,
      rate: this.player.getPlaybackRate() || 1, at: performance.now()};
  }

  observe() {
    if (!this.ready || !this.connected) return;
    const current = this.readPlayer();
    if (this.blocked) {
      if (!current.playing) return;
      this.blocked = false;
      this.onNotice('');
      this.startCorrection();
      return;
    }
    if (this.correction) {
      this.correct(current);
      return;
    }
    if (current.status === BUFFERING) {
      if (this.sample) this.sample.at = current.at;
      this.phaseChange = undefined;
      return;
    }
    const previous = this.sample;
    if (previous && previous.playing !== current.playing) {
      // A seek can briefly report pause or play while YouTube is still changing state.
      if (this.phaseChange?.playing !== current.playing) this.phaseChange = current;
      if (current.at - this.phaseChange.at < 160) return;
      this.recordIntent(current);
    } else if (previous) {
      const elapsed = (current.at - previous.at) / 1000;
      const expected = previous.position + (previous.playing ? elapsed * previous.rate : 0);
      const jumped = Math.abs(current.position - expected) > (current.playing ? 1.1 : 0.4);
      if (current.rate !== previous.rate || jumped) this.recordIntent(current);
      else if (!this.pending && !this.queued && this.state.playing && current.playing
               && Math.abs(current.position - this.roomPosition()) > 2.5) this.startCorrection();
    }
    this.phaseChange = undefined;
    this.sample = current;
  }

  recordIntent(current) {
    this.queued = {...current, videoId: this.state.video_id};
    this.sendIntent();
  }

  sendIntent() {
    if (this.pending || !this.queued) return;
    const intent = this.queued;
    this.queued = undefined;
    if (intent.videoId !== this.state.video_id) return;
    const elapsed = intent.playing ? (performance.now() - intent.at) / 1000 * intent.rate : 0;
    const position = Math.min(MAX_POSITION, intent.duration || MAX_POSITION, intent.position + elapsed);
    const requestId = ++this.sequence;
    if (!this.send({type: 'player', request_id: requestId, revision: this.state.revision,
      position, playing: intent.playing, rate: intent.rate})) return;
    this.pending = requestId;
    this.ackTimer = setTimeout(() => this.onTimeout(), 3500);
  }

  acknowledge(event) {
    if (event.request_id !== this.pending) {
      this.setState(event.playback);
      return;
    }
    this.setState(event.playback);
    clearTimeout(this.ackTimer);
    this.pending = undefined;
    // Acknowledging our own update does not touch the iframe, which can already be processing the next click.
    if (this.queued) this.sendIntent();
    else if (!event.accepted || event.playback.revision < this.state.revision) this.startCorrection();
  }

  startCorrection() {
    if (!this.ready || !this.connected) return;
    if (!this.state.playing && this.blocked) {
      this.blocked = false;
      this.onNotice('');
    }
    if (this.blocked) return;
    this.phaseChange = undefined;
    this.correction = {expires: performance.now() + 4000, nextCommand: 0};
    this.correct(this.readPlayer());
  }

  correct(current) {
    const correction = this.correction;
    const target = this.roomPosition();
    const playing = this.state.playing;
    const atEnd = current.status === ENDED && current.duration && target >= current.duration - 0.3;
    const drift = Math.abs(target - current.position);
    const setRate = current.rate !== this.state.rate && this.player.getAvailablePlaybackRates().includes(this.state.rate);
    const stable = current.status !== BUFFERING && (playing === current.playing || atEnd);
    if ((stable && drift <= (playing ? 1 : 0.55) && !setRate) || current.at >= correction.expires) {
      this.sample = current;
      this.correction = undefined;
      return;
    }
    if (current.at < correction.nextCommand) return;
    correction.nextCommand = current.at + 650;
    if (setRate) this.player.setPlaybackRate(this.state.rate);
    if (playing) {
      if (current.status === BUFFERING || atEnd) return;
      if (drift > 0.8) this.player.seekTo(target, true);
      if (!current.playing) this.player.playVideo();
    } else if (current.playing || current.status === BUFFERING) {
      this.player.pauseVideo();
    } else if (drift > 0.55) {
      if (current.status === PAUSED) {
        this.player.seekTo(target, true);
      } else {
        this.cuedAt = target;
        this.player.cueVideoById({videoId: this.state.video_id, startSeconds: target});
      }
    }
  }

  clearIntents() {
    clearTimeout(this.ackTimer);
    this.pending = undefined;
    this.queued = undefined;
  }

  unload() {
    clearTimeout(this.loadTimeout);
    this.clearIntents();
    this.generation++;
    this.player?.destroy();
    this.player = undefined;
    this.mount.replaceChildren();
    this.ready = false;
    this.failed = false;
    this.blocked = false;
    this.cuedAt = 0;
    this.sample = undefined;
    this.correction = undefined;
    this.phaseChange = undefined;
    this.onNotice('');
  }

  destroy() {
    clearInterval(this.interval);
    this.unload();
  }
}
