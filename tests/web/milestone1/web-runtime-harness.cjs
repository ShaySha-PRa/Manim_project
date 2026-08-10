"use strict";

const fs = require("fs");
const path = require("path");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const ts = require("typescript");

const ROOT = path.resolve(__dirname, "../../..");
const PLACEHOLDER = path.join(
  ROOT,
  "apps/web/src/components/feature-foundation/feature-placeholder.tsx",
);
const BUTTON = path.join(ROOT, "apps/web/src/components/ui/button.tsx");
const PANEL = path.join(ROOT, "apps/web/src/components/ui/panel.tsx");
const STATUS_MESSAGE = path.join(ROOT, "apps/web/src/components/ui/status-message.tsx");
const SESSION_HOOK = path.join(
  ROOT,
  "apps/web/src/hooks/workbench/use-workbench-session.ts",
);

function compileModule(sourcePath, dependencyMap) {
  const source = fs.readFileSync(sourcePath, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      esModuleInterop: true,
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: sourcePath,
  });
  const loadedModule = { exports: {} };
  const localRequire = (request) => {
    if (Object.hasOwn(dependencyMap, request)) {
      return dependencyMap[request];
    }
    return require(request);
  };

  new Function("require", "module", "exports", compiled.outputText)(
    localRequire,
    loadedModule,
    loadedModule.exports,
  );
  return loadedModule.exports;
}

function renderPlaceholderScenarios() {
  let activeSession;
  const jsxRuntime = require("react/jsx-runtime");
  const buttonModule = compileModule(BUTTON, { "react/jsx-runtime": jsxRuntime });
  const panelModule = compileModule(PANEL, { "react/jsx-runtime": jsxRuntime });
  const statusMessageModule = compileModule(STATUS_MESSAGE, {
    "react/jsx-runtime": jsxRuntime,
  });
  const placeholderModule = compileModule(PLACEHOLDER, {
    "../../hooks/workbench/use-workbench-session": {
      useWorkbenchSession: () => activeSession,
    },
    "../ui/button": buttonModule,
    "../ui/panel": panelModule,
    "../ui/status-message": statusMessageModule,
    "react/jsx-runtime": jsxRuntime,
  });
  const render = (name, session) => {
    activeSession = session;
    return renderToStaticMarkup(React.createElement(placeholderModule[name]));
  };
  const recover = () => undefined;

  return {
    loading: render("LabPlaceholder", {
      error: null,
      recover,
      state: "loading",
      user: null,
    }),
    error: render("LabPlaceholder", {
      error: "测试会话错误",
      recover,
      state: "error",
      user: null,
    }),
    labReady: render("LabPlaceholder", {
      error: null,
      recover,
      state: "ready",
      user: { email: "test@example.invalid", must_change_password: false },
    }),
    studioReady: render("StudioPlaceholder", {
      error: null,
      recover,
      state: "ready",
      user: { email: "test@example.invalid", must_change_password: false },
    }),
  };
}

function sameDependencies(left, right) {
  return (
    Array.isArray(left) &&
    Array.isArray(right) &&
    left.length === right.length &&
    left.every((value, index) => Object.is(value, right[index]))
  );
}

class ApiClientError extends Error {
  constructor(status) {
    super(`HTTP ${status}`);
    this.status = status;
  }
}

async function runSessionScenario(responses, retryAfterError = false) {
  const stateSlots = [];
  const callbackSlots = [];
  const effectSlots = [];
  const timers = new Map();
  const redirects = [];
  let cursor = 0;
  let nextTimerId = 1;
  let pendingEffects = [];
  let responseIndex = 0;

  const fakeReact = {
    useCallback(callback, dependencies) {
      const index = cursor++;
      const previous = callbackSlots[index];
      if (!previous || !sameDependencies(previous.dependencies, dependencies)) {
        callbackSlots[index] = { callback, dependencies };
      }
      return callbackSlots[index].callback;
    },
    useEffect(effect, dependencies) {
      const index = cursor++;
      const previous = effectSlots[index];
      if (!previous || !sameDependencies(previous.dependencies, dependencies)) {
        pendingEffects.push({ dependencies, effect, index });
      }
    },
    useState(initialValue) {
      const index = cursor++;
      if (!(index in stateSlots)) {
        stateSlots[index] =
          typeof initialValue === "function" ? initialValue() : initialValue;
      }
      const setState = (nextValue) => {
        stateSlots[index] =
          typeof nextValue === "function" ? nextValue(stateSlots[index]) : nextValue;
      };
      return [stateSlots[index], setState];
    },
  };
  const router = {
    replace(target) {
      redirects.push(target);
    },
  };
  const workbenchApi = {
    async session() {
      const response = responses[Math.min(responseIndex, responses.length - 1)];
      responseIndex += 1;
      if (response.type === "error") {
        throw new ApiClientError(response.status);
      }
      return {
        user: {
          email: "test@example.invalid",
          must_change_password: response.mustChangePassword,
        },
      };
    },
  };
  const originalWindow = global.window;
  global.window = {
    clearTimeout(timerId) {
      timers.delete(timerId);
    },
    setTimeout(callback) {
      const timerId = nextTimerId++;
      timers.set(timerId, callback);
      return timerId;
    },
  };

  try {
    const hookModule = compileModule(SESSION_HOOK, {
      "../../lib/api/client": { ApiClientError, workbenchApi },
      "next/navigation": { useRouter: () => router },
      react: fakeReact,
    });
    const render = () => {
      cursor = 0;
      pendingEffects = [];
      const result = hookModule.useWorkbenchSession();
      for (const pending of pendingEffects) {
        const previous = effectSlots[pending.index];
        if (previous && typeof previous.cleanup === "function") {
          previous.cleanup();
        }
        effectSlots[pending.index] = {
          cleanup: pending.effect(),
          dependencies: pending.dependencies,
        };
      }
      return result;
    };
    const runTimers = async () => {
      const callbacks = [...timers.values()];
      timers.clear();
      for (const callback of callbacks) {
        callback();
      }
      await new Promise((resolve) => setImmediate(resolve));
    };
    const states = [];
    let result = render();
    states.push(result.state);
    await runTimers();
    result = render();
    states.push(result.state);

    if (retryAfterError) {
      await result.recover();
      result = render();
      states.push(result.state);
    }

    return { error: result.error, redirects, states };
  } finally {
    global.window = originalWindow;
  }
}

async function executeSessionScenarios() {
  return {
    ready: await runSessionScenario([{ type: "success", mustChangePassword: false }]),
    errorThenRetry: await runSessionScenario(
      [
        { type: "error", status: 500 },
        { type: "success", mustChangePassword: false },
      ],
      true,
    ),
    unauthorized: await runSessionScenario([{ type: "error", status: 401 }]),
    mustChangePassword: await runSessionScenario([
      { type: "success", mustChangePassword: true },
    ]),
  };
}

async function main() {
  if (process.argv[2] === "placeholder") {
    process.stdout.write(JSON.stringify(renderPlaceholderScenarios()));
    return;
  }
  if (process.argv[2] === "session") {
    process.stdout.write(JSON.stringify(await executeSessionScenarios()));
    return;
  }
  throw new Error("Expected placeholder or session command");
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
