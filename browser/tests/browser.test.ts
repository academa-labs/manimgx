import { describe, expect, test } from "bun:test";
import { readFile } from "node:fs/promises";
import { createContext, SourceTextModule, SyntheticModule } from "node:vm";
import type * as BrowserAPI from "../dist/index.js";

const bundle = await readFile(new URL("../dist/manimgx.js", import.meta.url), "utf8");
const packageJSON = (await Bun.file(new URL("../package.json", import.meta.url)).json()) as {
  version: string;
};

// Each page gets its own globals and module, just as separate browser tabs do. Loading the
// emitted file also catches packaging mistakes that importing the TypeScript source misses.
async function page(script: string | null = null) {
  const tasks: (() => void)[] = [];
  const blobs: Blob[] = [];
  const elements = new Map<string, unknown>();
  const workers: Director[] = [];
  const waiting = { textContent: "", remove() {} };
  const canvas = {
    width: 0,
    height: 0,
    getBoundingClientRect: () => ({ width: 320, height: 180 }),
  };

  class Element extends EventTarget {
    isConnected = true;
    tabIndex = -1;
    attributes = new Map<string, string>();
    shadowRoot = {
      innerHTML: "",
      querySelector: (selector: string) => (selector === "canvas" ? canvas : waiting),
      append() {},
    };
    attachShadow() {
      return this.shadowRoot;
    }
    querySelector() {
      return script === null ? null : { textContent: script };
    }
    hasAttribute(name: string) {
      return this.attributes.has(name);
    }
    getAttribute(name: string) {
      return this.attributes.get(name) ?? null;
    }
    setAttribute(name: string, value: string) {
      this.attributes.set(name, value);
      this.attributeChangedCallback();
    }
    removeAttribute(name: string) {
      this.attributes.delete(name);
      this.attributeChangedCallback();
    }
    attributeChangedCallback() {}
  }

  class Director {
    sent: unknown[] = [];
    onmessage: ((event: { data: unknown }) => Promise<void>) | null = null;
    constructor(
      readonly url: string,
      readonly options: WorkerOptions,
    ) {
      workers.push(this);
    }
    postMessage(data: unknown) {
      this.sent.push(data);
    }
  }

  const context = createContext({
    HTMLElement: Element,
    navigator: { platform: "Linux" },
    customElements: {
      get: (name: string) => elements.get(name),
      define: (name: string, value: unknown) => elements.set(name, value),
    },
    Worker: Director,
    Blob,
    URL: class extends URL {
      static override createObjectURL(blob: Blob) {
        blobs.push(blob);
        return `blob:test/${blobs.length}`;
      }
    },
    devicePixelRatio: 2,
    setTimeout: (callback: () => void) => tasks.push(callback),
  });
  const module = new SourceTextModule(bundle, { context });
  await module.link(() => {
    throw new Error("The published player must be one self-contained module");
  });
  await module.evaluate();
  const api = module.namespace as typeof BrowserAPI;
  return {
    api,
    blobs,
    elements,
    workers,
    waiting,
    canvas,
    flush: () => tasks.splice(0).forEach((task) => task()),
  };
}

async function settle() {
  // Boot, micropip installation and queued runs all yield to promises. The worker's explicit
  // task boundary stays under the test's control, so these checks don't depend on wall time.
  for (let i = 0; i < 30; i++) await Promise.resolve();
}

describe("published browser module", () => {
  test("registers the public element and pins the Python package to its own version", async () => {
    const { api, elements, workers } = await page();
    expect(elements.get("manimgx-player")).toBe(api.ManimgxPlayer);
    expect(api.settings.manimgx).toBe(`manimgx==${packageJSON.version}`);
    expect(workers).toHaveLength(0);
  });

  test("keeps playback requests made before the engine arrives", async () => {
    const { api } = await page();
    const player = new api.ManimgxPlayer();
    expect(player.source).toBeNull();
    expect(player.scene).toBeNull();
    expect(player.duration).toBeNaN();
    expect(player.paused).toBe(true);
    player.setAttribute("autoplay", "");
    expect(player.paused).toBe(false);
    player.pause();
    expect(player.paused).toBe(true);
    player.play();
    expect(player.paused).toBe(false);
    player.currentTime = 2.5;
    player.currentTime = NaN;
    player.currentTime = Infinity;
    expect(player.currentTime).toBe(2.5);
    player.scene = "SecondScene";
    expect(player.scene).toBe("SecondScene");
    expect(player.currentTime).toBe(0);
    player.source = "class SecondScene(Scene): pass";
    expect(player.source).toBe("class SecondScene(Scene): pass");
    player.source = null;
    player.scene = null;
    expect(player.source).toBeNull();
    expect(player.scene).toBeNull();
  });

  test("boots once after settings are set and sends dedented scenes and subsequent edits", async () => {
    const state = await page("\n    class Demo(Scene):\n        pass\n  ");
    const player = new state.api.ManimgxPlayer();
    player.connectedCallback();
    state.api.settings.pyodide = "https://example.test/python/";
    state.api.settings.manimgx = "https://example.test/manimgx.whl";
    expect(state.workers).toHaveLength(0);
    state.flush();
    const director = state.workers[0]!;
    expect(director.options).toEqual({ type: "module" });
    expect(director.sent).toEqual([
      {
        boot: {
          pyodide: "https://example.test/python/",
          manimgx: "https://example.test/manimgx.whl",
        },
      },
      { film: 1, run: { source: "class Demo(Scene):\n    pass\n", scene: null } },
    ]);
    expect(state.canvas).toMatchObject({ width: 640, height: 360 });
    expect(player.tabIndex).toBe(0);
    await director.onmessage!({ data: { status: "Installing manimgx…" } });
    expect(state.waiting.textContent).toBe("Installing manimgx…");
    player.source = "class Changed(Scene): pass";
    expect(director.sent.at(-1)).toEqual({ film: 1, run: { source: player.source, scene: null } });
    player.scene = "Changed";
    expect(director.sent.at(-1)).toEqual({
      film: 1,
      run: { source: player.source, scene: "Changed" },
    });
    player.disconnectedCallback();
    player.connectedCallback();
    state.flush();
    expect(state.workers).toHaveLength(1);
    expect(director.sent).toHaveLength(4);
  });

  test("the embedded worker coalesces edits and isolates film failures", async () => {
    const state = await page();
    new state.api.ManimgxPlayer().connectedCallback();
    state.flush();
    const source = await state.blobs[0]!.text();
    const messages: { data: unknown; transfer: unknown[] }[] = [];
    const imports: string[] = [];
    const installs: string[] = [];
    const runs: { film: number; source: string; scene: string | null; tried: string[] }[] = [];
    const tasks: (() => void)[] = [];
    let destroyed = false;
    let allowBoot!: () => void;
    const bootGate = new Promise<void>((resolve) => {
      allowBoot = resolve;
    });
    const wasm = new Uint8Array([0, 97, 115, 109]);
    const fonts = [new Uint8Array([1, 2])];
    const runner = (
      film: number,
      source: string,
      scene: string | null,
      send: (bytes: Uint8Array) => void,
      tried: string[],
    ) => {
      if (source === "broken runner") throw new Error("Python worker failure");
      runs.push({ film, source, scene, tried: [...tried] });
      if (source === "latest" && !tried.includes("networkx")) return "networkx";
      send(new Uint8Array([film]));
      return null;
    };
    const pyodide = {
      loadPackage: async (name: string) => {
        expect(name).toBe("micropip");
      },
      pyimport: (name: string) => {
        expect(name).toBe("micropip");
        return {
          install: async (requirement: string) => {
            installs.push(requirement);
          },
        };
      },
      runPython: (source: string) =>
        source.includes("def run(")
          ? runner
          : source.startsWith("lambda text:")
            ? (text: string) => new TextEncoder().encode(text)
            : {
                toJs: () => ["engine source", wasm, fonts],
                destroy: () => {
                  destroyed = true;
                },
              },
      loadPackagesFromImports: async (source: string) => {
        if (source === "broken imports") throw new Error("Package download failed");
        imports.push(source);
      },
    };
    const global = {
      onmessage: null as ((event: { data: unknown }) => void) | null,
      postMessage: (data: unknown, transfer: unknown[] = []) => {
        messages.push({ data, transfer });
      },
      setTimeout: (callback: () => void) => tasks.push(callback),
    };
    const context = createContext(global);
    const pythonModule = new SyntheticModule(
      ["loadPyodide"],
      function () {
        this.setExport("loadPyodide", async (options: { indexURL: string }) => {
          expect(options.indexURL).toBe("https://example.test/python/");
          await bootGate;
          return pyodide;
        });
      },
      { context },
    );
    await pythonModule.link(() => {
      throw new Error("Unexpected dependency");
    });
    await pythonModule.evaluate();
    const worker = new SourceTextModule(source, {
      context,
      importModuleDynamically: (specifier) => {
        expect(specifier).toBe("https://example.test/python/pyodide.mjs");
        return pythonModule;
      },
    });
    await worker.link(() => {
      throw new Error("The embedded director must be self-contained");
    });
    await worker.evaluate();
    const send = (data: unknown) => global.onmessage!({ data });
    send({ boot: { pyodide: "https://example.test/python/", manimgx: "manimgx==test" } });
    send({ film: 1, run: { source: "stale", scene: null } });
    send({ film: 1, run: { source: "latest", scene: "Demo" } });
    send({ film: 2, run: { source: "other", scene: null } });
    allowBoot();
    await settle();
    expect(installs).toEqual(["manimgx==test", "networkx"]);
    expect(destroyed).toBe(true);
    expect(messages.slice(0, 3)).toEqual([
      { data: { status: "Loading Python…" }, transfer: [] },
      { data: { status: "Installing manimgx…" }, transfer: [] },
      {
        data: { engine: { js: "engine source", wasm, fonts } },
        transfer: [wasm.buffer, fonts[0]!.buffer],
      },
    ]);
    expect(runs).toEqual([
      { film: 1, source: "latest", scene: "Demo", tried: [] },
      { film: 1, source: "latest", scene: "Demo", tried: ["networkx"] },
    ]);
    tasks.splice(0).forEach((task) => task());
    await settle();
    expect(imports).toEqual(["latest", "other"]);
    expect(runs.at(-1)).toEqual({ film: 2, source: "other", scene: null, tried: [] });
    const feeds = messages.slice(3) as {
      data: { film: number; feed: ArrayBuffer };
      transfer: unknown[];
    }[];
    expect(feeds.map(({ data }) => [data.film, ...new Uint8Array(data.feed)])).toEqual([
      [1, 1],
      [2, 2],
    ]);
    for (const { data, transfer } of feeds) expect(transfer).toEqual([data.feed]);

    // A failed dependency load or Python call belongs to one film. It must not lock the
    // shared queue, and editing that same film must remain possible afterward.
    for (const [source, error] of [
      ["broken imports", "Package download failed"],
      ["broken runner", "Python worker failure"],
    ]) {
      tasks.splice(0).forEach((task) => task());
      await settle();
      send({ film: 3, run: { source, scene: null } });
      send({ film: 4, run: { source: "next film", scene: null } });
      await settle();
      const failed = messages.at(-1)!.data as { film: number; feed: ArrayBuffer };
      expect(failed.film).toBe(3);
      expect(JSON.parse(new TextDecoder().decode(failed.feed))).toEqual({
        error: { message: error, type: "Error" },
      });
      tasks.splice(0).forEach((task) => task());
      await settle();
      expect(runs.at(-1)).toMatchObject({ film: 4, source: "next film" });
      send({ film: 3, run: { source: "corrected", scene: null } });
      tasks.splice(0).forEach((task) => task());
      await settle();
      expect(runs.at(-1)).toMatchObject({ film: 3, source: "corrected" });
    }
  });
});
