import '@testing-library/jest-dom';

// jsdom doesn't implement ResizeObserver — used by SubtitleOverlay to track
// the video container's height for ASS-style font scaling.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// @ts-expect-error attaching to globalThis intentionally for jsdom tests
globalThis.ResizeObserver = globalThis.ResizeObserver ?? ResizeObserverStub;

// jsdom logs a "Not implemented" stack for HTMLMediaElement.play/pause; tests
// hit this when the EditorTab's hidden dub <audio> is rendered. The methods
// are no-ops in tests since playback isn't observable in jsdom anyway.
Object.defineProperty(window.HTMLMediaElement.prototype, 'play', {
  configurable: true,
  value: () => Promise.resolve(),
});
Object.defineProperty(window.HTMLMediaElement.prototype, 'pause', {
  configurable: true,
  value: () => {},
});
