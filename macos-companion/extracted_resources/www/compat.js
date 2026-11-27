// Compatibility shims for mobile browsers, old Android System WebViews, and Apple iOS / iPhone Safari.
(function () {
  'use strict';

  // 1. DOM and ES API shims (Chromium 83-92, older Safari)
  var proto = window.Element && window.Element.prototype;
  if (proto && typeof proto.replaceChildren !== 'function') {
    var replaceChildren = function () {
      while (this.firstChild) this.removeChild(this.firstChild);
      if (arguments.length) this.append.apply(this, arguments);
    };
    [window.Element, window.Document, window.DocumentFragment].forEach(function (ctor) {
      if (ctor && ctor.prototype && typeof ctor.prototype.replaceChildren !== 'function') {
        ctor.prototype.replaceChildren = replaceChildren;
      }
    });
  }

  // Array.prototype.at
  if (!Array.prototype.at) {
    Array.prototype.at = function (index) {
      var length = this.length >>> 0;
      var k = Math.trunc(index) || 0;
      if (k < 0) k += length;
      return k < 0 || k >= length ? undefined : this[k];
    };
  }

  // String.prototype.replaceAll
  if (!String.prototype.replaceAll) {
    String.prototype.replaceAll = function (search, replacement) {
      if (search instanceof RegExp) {
        if (!search.global) throw new TypeError('replaceAll must be called with a global RegExp');
        return this.replace(search, replacement);
      }
      return this.split(String(search)).join(replacement);
    };
  }

  // 2. iOS / iPhone Detection
  var ua = navigator.userAgent || '';
  var isIOS = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  window.__isPhoneBoxIOS = isIOS;

  // 3. AudioContext & Haptic Feedback for iOS Safari
  var audioCtx = null;
  function getAudioCtx() {
    if (!audioCtx && (window.AudioContext || window.webkitAudioContext)) {
      var Ctor = window.AudioContext || window.webkitAudioContext;
      audioCtx = new Ctor();
    }
    return audioCtx;
  }

  // Unlock audio context on first touch for iOS
  function unlockAudio() {
    var ctx = getAudioCtx();
    if (ctx && ctx.state === 'suspended') {
      ctx.resume().catch(function () {});
    }
    document.removeEventListener('touchstart', unlockAudio, true);
    document.removeEventListener('touchend', unlockAudio, true);
    document.removeEventListener('click', unlockAudio, true);
  }
  document.addEventListener('touchstart', unlockAudio, { capture: true, passive: true });
  document.addEventListener('touchend', unlockAudio, { capture: true, passive: true });
  document.addEventListener('click', unlockAudio, { capture: true, passive: true });

  // Provide synthetic micro-haptic sound feedback on iOS when vibration is requested
  function playHapticTick() {
    try {
      var ctx = getAudioCtx();
      if (!ctx || ctx.state !== 'running') return;
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(140, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(30, ctx.currentTime + 0.04);
      gain.gain.setValueAtTime(0.08, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.04);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.04);
    } catch (_) {}
  }

  if (!navigator.vibrate) {
    navigator.vibrate = function (pattern) {
      if (isIOS) {
        playHapticTick();
        return true;
      }
      return false;
    };
  } else {
    var origVibrate = navigator.vibrate.bind(navigator);
    navigator.vibrate = function (pattern) {
      try {
        var res = origVibrate(pattern);
        if (isIOS && !res) playHapticTick();
        return res;
      } catch (_) {
        if (isIOS) playHapticTick();
        return false;
      }
    };
  }

  // 4. iOS Screen WakeLock (Keep iPhone screen awake while acting as desk display)
  var wakeLockObj = null;
  async function requestWakeLock() {
    if ('wakeLock' in navigator && typeof navigator.wakeLock.request === 'function') {
      try {
        wakeLockObj = await navigator.wakeLock.request('screen');
        wakeLockObj.addEventListener('release', function () {
          wakeLockObj = null;
        });
      } catch (_) {}
    }
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') {
      requestWakeLock();
    }
  });
  window.addEventListener('focus', function () {
    requestWakeLock();
  });

  window.addEventListener('load', function () {
    requestWakeLock();
  });
  document.addEventListener('touchstart', function () {
    if (!wakeLockObj) requestWakeLock();
  }, { once: true, passive: true });

  // 5. Prevent iOS elastic rubberband / bounce on root viewport
  document.addEventListener('touchmove', function (e) {
    var target = e.target;
    var canScroll = false;
    while (target && target !== document.body) {
      var overflowY = window.getComputedStyle(target).overflowY;
      if ((overflowY === 'auto' || overflowY === 'scroll') && target.scrollHeight > target.clientHeight) {
        canScroll = true;
        break;
      }
      target = target.parentElement;
    }
    if (!canScroll && e.cancelable) {
      e.preventDefault();
    }
  }, { passive: false });

})();
