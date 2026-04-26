import "@testing-library/jest-dom/vitest";

class TestResizeObserver {
  observe(): void {
    // React Flow only needs the API to exist in jsdom smoke tests.
  }

  unobserve(): void {
    // React Flow only needs the API to exist in jsdom smoke tests.
  }

  disconnect(): void {
    // React Flow only needs the API to exist in jsdom smoke tests.
  }
}

globalThis.ResizeObserver = TestResizeObserver;
