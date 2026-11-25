import assert from 'node:assert/strict';
import test from 'node:test';
import {YouTubeSync} from '../js/player.js';

function playerHarness(t, initialStatus, initialPosition) {
  const sent = [];
  const sync = new YouTubeSync({replaceChildren() {}}, (command) => sent.push(command), () => {}, () => {});
  clearInterval(sync.interval);
  t.after(() => sync.destroy());
  let at = performance.now();
  t.mock.method(performance, 'now', () => at);
  const now = new Date().toISOString();
  const state = {video_id: 'M7lc1UVf-VE', position: initialPosition, playing: initialStatus === 1,
    rate: 1, revision: 1, updated_at: now};
  const player = {
    position: initialPosition, status: initialStatus, pauseCalls: 0,
    getCurrentTime() { return this.position; },
    getPlayerState() { return this.status; },
    getDuration() { return 120; },
    getPlaybackRate() { return 1; },
    getAvailablePlaybackRates() { return [1]; },
    pauseVideo() { this.pauseCalls++; this.status = 2; },
    seekTo(position) { this.position = position; },
    destroy() {},
  };
  sync.player = player;
  sync.connected = true;
  sync.ready = true;
  sync.state = state;
  sync.observe();
  const sample = (status, position, milliseconds = 200) => {
    player.status = status;
    player.position = position;
    at += milliseconds;
    sync.observe();
  };
  const ack = (command) => sync.acknowledge({request_id: command.request_id, accepted: true,
    playback: {...state, revision: command.revision + 1, position: command.position, playing: command.playing}});
  return {sync, player, sent, sample, ack};
}

test('native playback continues when a paused seek is acknowledged during resume', (t) => {
  const {player, sent, sample, ack} = playerHarness(t, 2, 20);
  sample(2, 40);
  assert.equal(sent.length, 1);
  assert.deepEqual([sent[0].position, sent[0].playing], [40, false]);

  sample(3, 40);
  sample(1, 40);
  ack(sent[0]);
  sample(1, 40.2);

  assert.equal(sent.length, 2);
  assert.deepEqual([sent[1].revision, sent[1].playing], [2, true]);
  assert.equal(player.pauseCalls, 0);
  assert.equal(player.status, 1);
});

test('an in-flight command keeps the newest local action for the next revision', (t) => {
  const {sent, sample, ack} = playerHarness(t, 2, 20);
  sample(2, 40);
  sample(1, 70);
  sample(1, 70.2);
  assert.equal(sent.length, 1);

  ack(sent[0]);
  assert.equal(sent.length, 2);
  assert.deepEqual([sent[1].revision, sent[1].playing], [2, true]);
  assert.ok(sent[1].position >= 70);
});

test('applying a peer pause never publishes a second pause or seek', (t) => {
  const {sync, player, sent, sample} = playerHarness(t, 1, 20);
  sync.setState({...sync.state, position: 32, playing: false, revision: 2});
  sample(2, 20, 700);
  sample(2, 32);
  sample(2, 32);
  assert.equal(player.pauseCalls, 1);
  assert.equal(player.position, 32);
  assert.equal(sent.length, 0);
});
