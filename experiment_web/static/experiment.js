/**
 * MIST EEG Experiment — Web Frontend
 *
 * Replicates the PsychoPy experiment logic in the browser.
 * All timing uses performance.now() + requestAnimationFrame.
 * Communicates with the Flask backend for CSV logging and GUI control.
 */

// ================================ State ================================

const SKIP_KEY = "s";
const SKIP_KEY_UPPER = "S";

const state = {
  subjectId: "",
  session: "",
  age: "",
  sex: "",
  handedness: "",
  operator: "",
  csvPath: "",
  recordingSession: "",
  deviceStatus: null,
  experimentStartTime: 0,
  config: {},
  // shared across stages
  skipPressed: false,
  aborted: false,
  fatalUiError: false,
};

// ================================ Helpers ================================

/** Show one screen, hide all others. */
function showScreen(id) {
  const target = document.getElementById(id);
  if (!target) {
    state.fatalUiError = true;
    document.body.innerHTML =
      '<div class="screen" style="display:flex">' +
      '<div class="card card-large">' +
      '<div class="card-header accent-red"><h1>网页版本不一致</h1></div>' +
      '<div class="card-body text-center">' +
      '<p>实验网页服务仍在运行旧版本，无法显示当前页面。</p>' +
      '<p class="muted">请关闭旧的实验网页命令窗口，重新运行启动脚本，然后按 Ctrl+F5 刷新。</p>' +
      '</div></div></div>';
    throw new Error("Missing screen element: " + id);
  }
  document.querySelectorAll(".screen").forEach((el) => {
    el.style.display = "none";
  });
  target.style.display = "flex";
}

/** Format seconds as MM:SS. */
function fmtTime(seconds) {
  const s = Math.max(0, Math.ceil(seconds));
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return String(m).padStart(2, "0") + ":" + String(sec).padStart(2, "0");
}

/** Clamp a number between lo and hi. */
function clamp(v, lo, hi) {
  return Math.min(Math.max(v, lo), hi);
}

/** Random float in [min, max). */
function randRange(min, max) {
  return Math.random() * (max - min) + min;
}

/** Random integer in [min, max] inclusive. */
function randInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

// ================================ API ================================

async function apiLog(row) {
  try {
    await fetch("/api/log", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(row),
    });
  } catch (e) {
    console.warn("apiLog failed:", e);
  }
}

async function apiGuiStart(stageName) {
  try {
    const res = await fetch("/api/gui/start_stage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage_name: stageName }),
    });
    const data = await res.json();
    return { ok: res.ok && data.status === "ok", ...data };
  } catch (e) {
    console.warn("apiGuiStart failed:", e);
    return { ok: false, message: "无法连接实验服务器" };
  }
}

async function apiGuiStop() {
  try {
    const res = await fetch("/api/gui/stop", { method: "POST" });
    const data = await res.json();
    return { ok: res.ok && data.status === "ok", ...data };
  } catch (e) {
    console.warn("apiGuiStop failed:", e);
    return { ok: false, message: "无法连接实验服务器" };
  }
}

async function apiGuiStatus() {
  try {
    const res = await fetch("/api/gui/status", { cache: "no-store" });
    const data = await res.json();
    return { connected: false, ready: false, ...data };
  } catch (e) {
    return {
      connected: false,
      ready: false,
      message: "实验服务器不可达，请检查启动窗口",
    };
  }
}

async function startExperimentSession() {
  const res = await fetch("/api/experiment/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      subject_id: state.subjectId,
      session: state.session,
    }),
  });
  const data = await res.json();
  if (!res.ok || data.status !== "ok") {
    throw new Error(data.gui?.message || data.message || "无法创建实验会话");
  }
  state.subjectId = data.subject_id;
  state.session = data.session;
  state.csvPath = data.csv_path;
  state.recordingSession = data.recording_session;
}

// ================================ Keyboard ================================

let _keyQueue = [];

function isEditableKeyTarget(target) {
  if (!(target instanceof HTMLElement)) return false;
  const editable = target.closest("input, textarea, select, [contenteditable='true']");
  if (!editable) return false;
  const isDisabled = "disabled" in editable && editable.disabled;
  const isReadOnly = "readOnly" in editable && editable.readOnly;
  return editable.offsetParent !== null && !isDisabled && !isReadOnly;
}

function onKeyDown(e) {
  if (isEditableKeyTarget(e.target)) return;

  // Block default for keys we care about
  if ([" ", "Escape", "Enter", "Backspace", "s", "S"].includes(e.key) ||
      /^[0-9]$/.test(e.key) || e.key === "-") {
    e.preventDefault();
  }
  _keyQueue.push(e.key);
}

document.addEventListener("keydown", onKeyDown);

/** Get all keys pressed since last call. */
function getKeys() {
  const keys = _keyQueue;
  _keyQueue = [];
  return keys;
}

/** Clear any pending keys. */
function clearKeys() {
  _keyQueue = [];
}

/** Wait for a specific set of keys, returning the first match. Returns null on timeout (seconds). */
function waitForKey(keyList, timeoutSec = Infinity) {
  return new Promise((resolve) => {
    const start = performance.now();
    function check() {
      const keys = _keyQueue;
      _keyQueue = [];
      for (const k of keys) {
        if (keyList.includes(k)) {
          return resolve(k);
        }
      }
      if (timeoutSec !== Infinity && (performance.now() - start) / 1000 >= timeoutSec) {
        return resolve(null);
      }
      requestAnimationFrame(check);
    }
    check();
  });
}

/** Check if the skip key was in a list of keys. Also sets state.skipPressed. */
function checkSkip(keys) {
  if (keys.includes(SKIP_KEY) || keys.includes(SKIP_KEY_UPPER)) {
    state.skipPressed = true;
    return true;
  }
  return false;
}

/** Check if escape was pressed. */
function checkAbort(keys) {
  if (keys.includes("Escape")) {
    state.aborted = true;
    return true;
  }
  return false;
}

// ================================ Math Problem Generation ================================

function generateProblem(condition) {
  let a, b, op;
  if (condition === "practice") {
    a = randInt(2, 12);
    b = randInt(2, 12);
    op = Math.random() < 0.5 ? "+" : "-";
  } else if (condition === "control") {
    a = randInt(6, 24);
    b = randInt(2, 18);
    const ops = ["+", "-", "*"];
    op = ops[randInt(0, 2)];
  } else {
    // stress
    a = randInt(12, 48);
    b = randInt(3, 19);
    const ops = ["+", "-", "*"];
    op = ops[randInt(0, 2)];
  }

  let trueValue;
  if (op === "+") trueValue = a + b;
  else if (op === "-") trueValue = a - b;
  else trueValue = a * b;

  return {
    expression: a + " " + op + " " + b,
    a, b, operator: op,
    true_value: trueValue,
    correct_answer: String(trueValue),
  };
}

// ================================ Stress Logic ================================

function updateStressDeadline(deadline, correctHistory, config) {
  if (correctHistory.length < 5) return deadline;
  const recent = correctHistory.slice(-8);
  const recentRate = recent.filter(Boolean).length / recent.length;
  if (recentRate > config.target_success_rate) {
    deadline -= 0.18;
  } else {
    deadline += 0.12;
  }
  return clamp(deadline, config.stress_deadline_min, config.stress_deadline_max);
}

function estimateStressDeadline(controlRTs, config) {
  if (controlRTs.length < 3) return config.stress_deadline_start;
  const sorted = [...controlRTs].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  return clamp(median * 0.85, config.stress_deadline_min, config.stress_deadline_max);
}

function deriveStressTargets(controlAccuracy, config) {
  const controlPercent = Math.round(controlAccuracy * 100);
  const target = clamp(controlPercent + config.stress_target_boost,
    config.stress_target_min, config.stress_target_max);
  const peerAvg = clamp(controlPercent + config.peer_boost, 70, Math.max(70, target - 2));
  return { peerAvg, target };
}

// ================================ Subject Info ================================

async function runSubjectInfo() {
  showScreen("screen-subject-info");

  // Focus first field
  document.getElementById("fld-subject-id").focus();

  return new Promise((resolve) => {
    async function onEnter(e) {
      if (e.key === "Enter") {
        e.preventDefault();
        document.removeEventListener("keydown", onEnter);
        // Collect values
        state.subjectId = document.getElementById("fld-subject-id").value.trim() || "TEST";
        state.session = document.getElementById("fld-session").value.trim() || "01";
        state.age = document.getElementById("fld-age").value.trim();
        state.sex = document.querySelector('input[name="sex"]:checked')?.value || "male";
        state.handedness = document.querySelector('input[name="handedness"]:checked')?.value || "right";
        state.operator = document.getElementById("fld-operator").value.trim();

        document.activeElement?.blur();
        resolve();
      }
      if (e.key === "Escape") {
        state.aborted = true;
        document.removeEventListener("keydown", onEnter);
        document.activeElement?.blur();
        resolve();
      }
    }
    document.addEventListener("keydown", onEnter);
  });
}

// ================================ EEG Device Check ================================

function setDeviceBadge(id, ok, waiting = false) {
  const element = document.getElementById(id);
  if (!element) return;
  element.textContent = waiting ? "检测中" : (ok ? "已就绪" : "未就绪");
  element.className = "device-badge " +
    (waiting ? "device-waiting" : (ok ? "device-ok" : "device-error"));
}

function renderDeviceStatus(status, options = {}) {
  state.deviceStatus = status;
  setDeviceBadge("device-gui", status.connected && status.control_api);
  setDeviceBadge("device-session", status.session_started);
  setDeviceBadge("device-source", status.ads1299_selected);
  setDeviceBadge("device-board", status.ads1299_connected);

  const title = document.getElementById("device-check-title");
  const header = document.getElementById("device-check-header");
  const message = document.getElementById("device-check-message");
  if (title) title.textContent = options.title || "正在检查脑电设备";
  if (header) header.className = "card-header " +
    (status.ready ? "accent-green" : "accent-blue");
  if (message) message.textContent = options.message || status.message || "正在检测设备状态";
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForGuiReady(options = {}) {
  showScreen("screen-device-check");
  clearKeys();
  const footer = document.getElementById("device-check-footer");
  if (footer) footer.innerHTML = "系统会自动重试；按 <kbd>Esc</kbd> 中止实验";

  while (!state.aborted) {
    const status = await apiGuiStatus();
    renderDeviceStatus(status, options);
    if (status.ready) {
      if (footer) footer.textContent = "检测通过，正在继续…";
      await sleep(350);
      return true;
    }
    if (getKeys().includes("Escape")) {
      state.aborted = true;
      return false;
    }
    await sleep(750);
  }
  return false;
}

async function ensureGuiStageStarted(stageName) {
  while (!state.aborted) {
    const result = await apiGuiStart(stageName);
    if (result.ok) return true;
    const ready = await waitForGuiReady({
      title: "脑电采集尚未开始",
      message: result.message || result.gui?.message || "正在恢复设备连接",
    });
    if (!ready) return false;
  }
  return false;
}

async function ensureGuiStopped(required = true) {
  let attempts = 0;
  while (true) {
    const result = await apiGuiStop();
    if (result.ok) return true;

    const status = await apiGuiStatus();
    if (status.connected && !status.streaming && !status.recording) return true;
    attempts += 1;
    if (!required && attempts >= 2) return false;

    showScreen("screen-device-check");
    renderDeviceStatus(status, {
      title: "正在停止采集并保存数据",
      message: result.message || status.message || "等待 GUI 保存当前阶段文件",
    });
    await sleep(750);
  }
}

// ================================ Instructions ================================

async function runInstructions() {
  showScreen("screen-instructions");
  clearKeys();

  while (true) {
    const key = await waitForKey([" ", "Escape", SKIP_KEY, SKIP_KEY_UPPER]);
    if (key === "Escape") { state.aborted = true; return; }
    if (key === " " || key === SKIP_KEY || key === SKIP_KEY_UPPER) return;
  }
}

// ================================ Rest Block ================================

async function runRestBlock(stage, title, instruction, showFixation) {
  const config = state.config;
  const duration = config[stage + "_sec"] || 180;

  // Instructions page
  showScreen("screen-instructions");
  document.querySelector("#screen-instructions .card-header h1").textContent = title;
  document.querySelector("#screen-instructions .card-body").innerHTML =
    `<p>${instruction}</p><br><p id="rest-instruction-countdown" class="muted">本阶段时长：${fmtTime(duration)}</p>`;
  document.querySelector("#screen-instructions .card-header").className =
    "card-header accent-blue";
  document.querySelector("#screen-instructions .card-footer .hint").innerHTML =
    "按 <kbd>空格</kbd> 开始；按 <kbd>S</kbd> 跳过";

  clearKeys();
  const startKey = await waitForKey([" ", "Escape", SKIP_KEY, SKIP_KEY_UPPER]);
  if (startKey === "Escape") { state.aborted = true; return { skipped: false }; }
  if (checkSkip([startKey])) {
    await apiLog({
      row_type: "block", stage, condition: stage,
      event: "skip_before_start", skipped: true,
    });
    return { skipped: true };
  }

  // Start GUI streaming only after the GUI confirms ADS1299 readiness.
  if (!await ensureGuiStageStarted(stage)) {
    return { skipped: false };
  }

  await apiLog({
    row_type: "block", stage, condition: stage,
    event: "block_start", skipped: false,
    time_global: performance.now() / 1000,
  });

  // Keep this stage on the same card and turn the duration label into a countdown.
  showScreen("screen-instructions");
  const instructionCountdown = document.getElementById("rest-instruction-countdown");
  if (instructionCountdown) {
    instructionCountdown.textContent = `剩余时间：${fmtTime(duration)}`;
  }
  document.querySelector("#screen-instructions .card-footer .hint").innerHTML =
    "请保持放松；按 <kbd>S</kbd> 跳过";

  document.getElementById("rest-stage-title").textContent = title;
  document.getElementById("rest-instruction").textContent = instruction;
  document.getElementById("rest-fixation").style.display = showFixation ? "block" : "none";

  const startTime = performance.now();
  state.skipPressed = false;

  return new Promise((resolve) => {
    let finishing = false;

    async function finish(event, skipped, elapsed) {
      if (finishing) return;
      finishing = true;
      await ensureGuiStopped(!state.aborted);
      if (event) {
        await apiLog({
          row_type: "block", stage, condition: stage,
          event, skipped,
          time_global: performance.now() / 1000,
          duration: elapsed,
        });
      }
      resolve({ skipped });
    }

    function frame() {
      if (state.aborted) {
        finish(null, false, (performance.now() - startTime) / 1000);
        return;
      }

      const elapsed = (performance.now() - startTime) / 1000;
      const remaining = duration - elapsed;
      const progress = Math.min(elapsed / duration, 1.0);

      // Update UI
      if (instructionCountdown) {
        instructionCountdown.textContent = `剩余时间：${fmtTime(remaining)}`;
      }
      document.getElementById("rest-countdown").textContent = fmtTime(remaining);
      document.getElementById("rest-progress").style.width = (progress * 100) + "%";
      document.getElementById("rest-timer").textContent = fmtTime(remaining);

      // Check keys
      const keys = getKeys();
      if (checkAbort(keys)) {
        finish(null, false, elapsed);
        return;
      }
      if (checkSkip(keys)) {
        finish("block_end_skipped", true, elapsed);
        return;
      }

      if (elapsed >= duration) {
        // Do not enter VAS/the next stage until GUI confirms the file is closed.
        finish("block_end", false, elapsed);
        return;
      }

      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  });
}

// ================================ VAS ================================

async function runVAS(afterStage) {
  showScreen("screen-vas");
  clearKeys();

  const barContainer = document.getElementById("vas-bar-container");
  const vasMarker = document.getElementById("vas-marker");
  const vasValueDisplay = document.getElementById("vas-value-display");
  let rating = null;

  const startTime = performance.now();

  // Click handler
  function onClick(e) {
    const rect = barContainer.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const ratio = clamp(x / rect.width, 0, 1);
    rating = Math.round(ratio * 100);
    rating = clamp(rating, 0, 100);

    vasMarker.style.display = "block";
    vasMarker.style.left = (ratio * 100) + "%";
    vasValueDisplay.textContent = rating;
  }

  barContainer.addEventListener("click", onClick);

  return new Promise((resolve) => {
    async function check() {
      if (state.aborted) {
        barContainer.removeEventListener("click", onClick);
        resolve({ skipped: false, rating });
        return;
      }

      const keys = getKeys();
      if (checkAbort(keys)) {
        barContainer.removeEventListener("click", onClick);
        resolve({ skipped: false, rating });
        return;
      }
      if (checkSkip(keys)) {
        barContainer.removeEventListener("click", onClick);
        await apiLog({
          row_type: "vas", stage: afterStage, condition: afterStage,
          event: "vas_skipped", skipped: true,
          time_global: performance.now() / 1000,
          rt: (performance.now() - startTime) / 1000,
        });
        resolve({ skipped: true, rating: null });
        return;
      }
      if (keys.includes(" ") && rating !== null) {
        barContainer.removeEventListener("click", onClick);
        await apiLog({
          row_type: "vas", stage: afterStage, condition: afterStage,
          event: "vas", skipped: false,
          time_global: performance.now() / 1000,
          vas_rating: rating,
          rt: (performance.now() - startTime) / 1000,
        });
        resolve({ skipped: false, rating });
        return;
      }

      requestAnimationFrame(check);
    }
    requestAnimationFrame(check);
  });
}

// ================================ Math Block ================================

async function runMathBlock(condition, title, opts = {}) {
  const config = state.config;
  const duration = config[condition + "_sec"] || 180;

  let deadline;
  let peerAverage = opts.peerAverage || 78;
  let stressTarget = opts.stressTarget || 85;

  if (condition === "practice") {
    deadline = config.practice_deadline;
  } else if (condition === "control") {
    deadline = config.control_deadline;
  } else {
    deadline = opts.initialDeadline || config.stress_deadline_start;
  }

  // Intro instruction
  let intro;
  if (condition === "practice") {
    intro = "练习阶段：请尽快且准确地计算结果。\n输入数字后按 Enter 提交。";
  } else if (condition === "control") {
    intro = "Control Math：请计算每道题的结果。\n本阶段反馈为中性，不显示同伴比较。";
  } else {
    intro = "Stress Math：请尽快且准确地作答。\n屏幕会显示当前表现、同伴平均表现和目标表现。\n错误或超时会出现负性反馈。";
  }

  showScreen("screen-instructions");
  document.querySelector("#screen-instructions .card-header h1").textContent = title;
  document.querySelector("#screen-instructions .card-body").innerHTML =
    `<p>${intro.replace(/\n/g, "<br>")}</p><br><p class="muted">本阶段时长：${fmtTime(duration)}</p>`;
  document.querySelector("#screen-instructions .card-header").className =
    condition === "stress" ? "card-header accent-red" : "card-header accent-blue";
  document.querySelector("#screen-instructions .card-footer .hint").innerHTML =
    "按 <kbd>空格</kbd> 继续；按 <kbd>S</kbd> 跳过";

  clearKeys();
  const startKey = await waitForKey([" ", "Escape", SKIP_KEY, SKIP_KEY_UPPER]);
  if (startKey === "Escape") { state.aborted = true; return { skipped: false, n_trials: 0, accuracy: 0, correct_rts: [], final_deadline: deadline }; }
  if (checkSkip([startKey])) {
    await apiLog({
      row_type: "block", stage: condition, condition,
      event: "skip_before_start", skipped: true,
    });
    return { skipped: true, n_trials: 0, accuracy: 0, correct_rts: [], final_deadline: deadline };
  }

  // Start GUI streaming only after the GUI confirms ADS1299 readiness.
  if (!await ensureGuiStageStarted(condition)) {
    return { skipped: false, n_trials: 0, accuracy: 0, correct_rts: [], final_deadline: deadline };
  }

  await apiLog({
    row_type: "block", stage: condition, condition,
    event: "block_start", skipped: false,
    time_global: performance.now() / 1000,
  });

  // Show math screen
  showScreen("screen-math");
  document.getElementById("math-stage-title").textContent = title;

  // Configure UI for condition
  const stressPanel = document.getElementById("stress-panel");
  const nonstressHint = document.getElementById("nonstress-hint");
  if (condition === "stress") {
    stressPanel.style.display = "flex";
    nonstressHint.style.display = "none";
    document.getElementById("math-progress").className = "progress-bar-fill progress-red";
    document.getElementById("stat-peer-avg").textContent = peerAverage + "%";
    document.getElementById("stat-target").textContent = stressTarget + "%";
  } else {
    stressPanel.style.display = "none";
    nonstressHint.style.display = "block";
    document.getElementById("math-progress").className = "progress-bar-fill progress-blue";
  }

  const blockStartTime = performance.now();
  let trialIndex = 0;
  const correctHistory = [];
  const validCorrectRTs = [];
  let skipped = false;
  state.skipPressed = false;

  // Main trial loop
  while (true) {
    if (state.aborted) {
      break;
    }

    const blockElapsed = (performance.now() - blockStartTime) / 1000;
    if (blockElapsed >= duration) break;

    // Check skip from prior iteration
    if (state.skipPressed) {
      skipped = true;
      break;
    }

    trialIndex++;
    const problem = generateProblem(condition);

    // ---- Fixation ----
    showScreen("screen-fixation");
    document.getElementById("math-progress").style.width =
      Math.min(blockElapsed / duration * 100, 100) + "%";
    document.getElementById("math-countdown").textContent =
      fmtTime(duration - blockElapsed);

    const fixationStart = performance.now();
    const fixationKeys = await waitForKey(
      ["Escape", SKIP_KEY, SKIP_KEY_UPPER],
      config.fixation_sec
    );
    if (fixationKeys) {
      if (fixationKeys === "Escape") { state.aborted = true; break; }
      if (checkSkip([fixationKeys])) { skipped = true; break; }
    }

    if (state.aborted) break;
    if (skipped) break;

    // ---- Problem Presentation ----
    showScreen("screen-math");
    document.getElementById("math-expression").textContent = problem.expression + " = ?";
    document.getElementById("math-answer").textContent = "";
    document.getElementById("deadline-bar").style.width = "100%";
    const deadlineBar = document.getElementById("deadline-bar");

    const currentPerf = correctHistory.length > 0
      ? (correctHistory.filter(Boolean).length / correctHistory.length * 100) : 0;

    if (condition === "stress") {
      document.getElementById("stat-current-perf").textContent = Math.round(currentPerf) + "%";
    }

    const problemOnset = performance.now() / 1000;
    const trialStart = performance.now();
    let response = "";
    let responseTime = null;
    let rt = null;
    let timeout = false;
    let trialSkipped = false;

    // Problem loop
    while (true) {
      const trialElapsed = (performance.now() - trialStart) / 1000;
      const deadlineLeft = deadline - trialElapsed;
      const blockElapsed2 = (performance.now() - blockStartTime) / 1000;

      // Update stage progress
      document.getElementById("math-countdown").textContent = fmtTime(duration - blockElapsed2);
      document.getElementById("math-progress").style.width =
        Math.min(blockElapsed2 / duration * 100, 100) + "%";

      // Update deadline bar
      const deadlineProgress = Math.max(0, Math.min(deadlineLeft / deadline, 1));
      deadlineBar.style.width = (deadlineProgress * 100) + "%";
      if (condition === "stress" && deadlineLeft < 1.0) {
        deadlineBar.className = "progress-bar-fill progress-red";
      } else {
        deadlineBar.className = "progress-bar-fill progress-blue";
      }

      // Update answer display
      document.getElementById("math-answer").textContent = response || "_";

      // Check timeout
      if (trialElapsed >= deadline) break;

      // Check keys
      const keys = getKeys();
      if (checkAbort(keys)) { state.aborted = true; break; }
      if (checkSkip(keys)) { trialSkipped = true; break; }

      for (const key of keys) {
        if (key === "Backspace") {
          response = response.slice(0, -1);
        } else if (key === "-" && response === "") {
          response = "-";
        } else if (key === "Enter") {
          if (response !== "" && response !== "-") {
            rt = trialElapsed;
            responseTime = performance.now() / 1000;
          }
        } else if (/^[0-9]$/.test(key)) {
          response += key;
        }
      }

      if (state.aborted || trialSkipped || rt !== null) break;

      // Use a small delay to avoid spinning at max FPS
      await new Promise(r => requestAnimationFrame(r));
    }

    if (state.aborted) break;
    if (trialSkipped) { skipped = true; break; }

    // Determine correctness
    if (!response || rt === null) {
      timeout = true;
    }
    const isCorrect = response === problem.correct_answer && !timeout;
    correctHistory.push(isCorrect);
    if (isCorrect && rt !== null) {
      validCorrectRTs.push(rt);
    }

    const deadlineUsed = deadline;

    // ---- Feedback ----
    let feedbackText, feedbackDetail, feedbackColor, feedbackType;
    if (condition === "stress") {
      if (timeout) {
        feedbackText = "太慢了";
        feedbackDetail = "你的反应速度低于目标表现";
        feedbackColor = "var(--red)";
        feedbackType = "negative_timeout";
      } else if (!isCorrect) {
        feedbackText = "错误";
        feedbackDetail = "你的准确率低于目标表现";
        feedbackColor = "var(--red)";
        feedbackType = "negative_error";
      } else {
        feedbackText = "正确";
        feedbackDetail = "请继续保持速度";
        feedbackColor = "var(--green)";
        feedbackType = "positive";
      }
      deadline = updateStressDeadline(deadline, correctHistory, config);
    } else if (condition === "control") {
      feedbackText = "已记录";
      feedbackDetail = "请继续下一题";
      feedbackColor = "var(--blue)";
      feedbackType = "neutral";
    } else {
      feedbackText = isCorrect ? "正确" : "错误或超时";
      feedbackDetail = "练习反馈";
      feedbackColor = isCorrect ? "var(--green)" : "var(--red)";
      feedbackType = isCorrect ? "practice_correct" : "practice_incorrect";
    }

    showScreen("screen-feedback");
    document.getElementById("feedback-text").textContent = feedbackText;
    document.getElementById("feedback-text").style.color = feedbackColor;
    document.getElementById("feedback-detail").textContent = feedbackDetail;

    // Wait for feedback duration (or skip)
    const feedbackKeys = await waitForKey(
      ["Escape", SKIP_KEY, SKIP_KEY_UPPER],
      config.feedback_sec
    );
    if (feedbackKeys) {
      if (feedbackKeys === "Escape") { state.aborted = true; break; }
      if (checkSkip([feedbackKeys])) { skipped = true; break; }
    }

    // ---- Log Trial ----
    await apiLog({
      row_type: "trial",
      stage: condition, condition,
      trial_index: trialIndex,
      problem: problem.expression + " = ?",
      a: problem.a, b: problem.b, operator: problem.operator,
      true_value: problem.true_value,
      shown_value: "", equation_is_true: "",
      correct_key: problem.correct_answer,
      response, rt, correct: isCorrect, timeout,
      deadline: deadlineUsed,
      feedback_type: feedbackType,
      problem_onset: problemOnset,
      response_time: responseTime,
      feedback_onset: performance.now() / 1000,
      time_global: performance.now() / 1000,
      current_performance: currentPerf,
      peer_average: condition === "stress" ? peerAverage : "",
      target_performance: condition === "stress" ? stressTarget : "",
      skipped: false,
    });

    if (state.aborted) break;
    if (skipped) break;

    // ---- ITI ----
    showScreen("screen-fixation");
    document.getElementById("math-expression").textContent = "";
    document.getElementById("math-answer").textContent = "";
    const itiDuration = randRange(config.iti_min, config.iti_max);
    const itiKeys = await waitForKey(
      ["Escape", SKIP_KEY, SKIP_KEY_UPPER],
      itiDuration
    );
    if (itiKeys) {
      if (itiKeys === "Escape") { state.aborted = true; break; }
      if (checkSkip([itiKeys])) { skipped = true; break; }
    }
  }

  // A completed stage is not allowed to advance until the recording is closed.
  await ensureGuiStopped(!state.aborted);

  const accuracy = correctHistory.length > 0
    ? correctHistory.filter(Boolean).length / correctHistory.length : 0;

  await apiLog({
    row_type: "block",
    stage: condition, condition,
    event: skipped ? "block_end_skipped" : "block_end",
    duration: (performance.now() - blockStartTime) / 1000,
    current_performance: accuracy * 100,
    skipped,
  });

  return {
    skipped,
    n_trials: correctHistory.length,
    accuracy,
    correct_rts: validCorrectRTs,
    final_deadline: deadline,
  };
}

// ================================ End Screen ================================

async function runEndScreen() {
  showScreen("screen-end");
  document.getElementById("end-csv-path").textContent = state.csvPath || "(N/A)";
  clearKeys();

  while (true) {
    const key = await waitForKey([" ", "Escape"]);
    if (key === " " || key === "Escape") return;
  }
}

async function runAbortScreen() {
  showScreen("screen-abort");
  document.getElementById("abort-csv-path").textContent = state.csvPath || "(N/A)";
  clearKeys();

  await apiLog({
    row_type: "experiment",
    event: "experiment_aborted",
    condition: "experiment",
    time_global: performance.now() / 1000,
  });

  while (true) {
    const key = await waitForKey([" ", "Escape"]);
    if (key === " " || key === "Escape") return;
  }
}

// ================================ Main Flow ================================

async function main() {
  // Load config from backend
  try {
    const res = await fetch("/api/experiment/config");
    state.config = await res.json();
  } catch (e) {
    console.warn("Failed to load config:", e);
    state.config = {};
  }

  try {
    // 1. Subject Info
    await runSubjectInfo();
    if (state.aborted) { await runAbortScreen(); return; }

    // 2. Verify the live GUI session and physical ADS1299 connection.
    if (!await waitForGuiReady()) { await runAbortScreen(); return; }
    try {
      await startExperimentSession();
    } catch (error) {
      // Device state can change between STATUS and session creation; retry safely.
      if (!await waitForGuiReady({ message: error.message })) {
        await runAbortScreen();
        return;
      }
      await startExperimentSession();
    }
    state.experimentStartTime = performance.now();
    await apiLog({
      row_type: "experiment",
      event: "experiment_start",
      condition: "experiment",
      time_global: performance.now() / 1000,
      condition_order: "control->stress",
      participant_age: state.age,
      participant_sex: state.sex,
      participant_handedness: state.handedness,
      experimenter_id: state.operator,
    });

    // 3. Instructions
    await runInstructions();
    if (state.aborted) { await runAbortScreen(); return; }

    // 4. Eyes Open
    let result = await runRestBlock("eyes_open", "睁眼静息", "请睁眼注视屏幕中央，保持放松。", true);
    if (state.aborted) { await runAbortScreen(); return; }
    await runVAS("eyes_open");
    if (state.aborted) { await runAbortScreen(); return; }

    // 5. Eyes Closed
    result = await runRestBlock("eyes_closed", "闭眼静息", "请闭上眼睛，保持清醒和放松。听到提示后再睁眼。", false);
    if (state.aborted) { await runAbortScreen(); return; }
    await runVAS("eyes_closed");
    if (state.aborted) { await runAbortScreen(); return; }

    // 6. Practice
    const practiceSummary = await runMathBlock("practice", "练习阶段");
    if (state.aborted) { await runAbortScreen(); return; }
    await runVAS("practice");
    if (state.aborted) { await runAbortScreen(); return; }

    // 7. Control
    const controlSummary = await runMathBlock("control", "Control Math");
    if (state.aborted) { await runAbortScreen(); return; }
    await runVAS("control");
    if (state.aborted) { await runAbortScreen(); return; }

    // 8. Stress — derive targets from control performance
    const targets = deriveStressTargets(controlSummary.accuracy, state.config);
    const stressDeadline = estimateStressDeadline(controlSummary.correct_rts, state.config);

    await apiLog({
      row_type: "experiment",
      event: "control_summary",
      condition: "experiment",
      practice_accuracy: practiceSummary.accuracy,
      control_accuracy: controlSummary.accuracy,
      stress_initial_deadline: stressDeadline,
      peer_average: targets.peerAvg,
      target_performance: targets.target,
      time_global: performance.now() / 1000,
    });

    await runMathBlock("stress", "Stress Math", {
      initialDeadline: stressDeadline,
      peerAverage: targets.peerAvg,
      stressTarget: targets.target,
    });
    if (state.aborted) { await runAbortScreen(); return; }
    await runVAS("stress");
    if (state.aborted) { await runAbortScreen(); return; }

    // 9. Recovery
    result = await runRestBlock("recovery", "Recovery", "请安静休息，尽量放松。", false);
    if (state.aborted) { await runAbortScreen(); return; }
    await runVAS("recovery");
    if (state.aborted) { await runAbortScreen(); return; }

    // 10. Experiment End
    await apiLog({
      row_type: "experiment",
      event: "experiment_end",
      condition: "experiment",
      time_global: performance.now() / 1000,
    });

    await runEndScreen();

  } finally {
    // Best-effort emergency cleanup. Normal stage transitions already wait for save.
    await ensureGuiStopped(false);
  }
}

// ================================ Start ================================

main().catch(async (err) => {
  console.error("Experiment crashed:", err);
  if (state.fatalUiError) {
    await ensureGuiStopped(false);
    return;
  }
  state.aborted = true;
  await ensureGuiStopped(false);
  await runAbortScreen();
});

// A refresh/closed tab must not leave an unattended EEG recording running.
window.addEventListener("pagehide", () => {
  if (state.recordingSession && navigator.sendBeacon) {
    navigator.sendBeacon("/api/gui/stop");
  }
});
