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
  guiConnected: false,
  experimentStartTime: 0,
  config: {},
  // shared across stages
  skipPressed: false,
  aborted: false,
};

// ================================ Helpers ================================

/** Show one screen, hide all others. */
function showScreen(id) {
  document.querySelectorAll(".screen").forEach((el) => {
    el.style.display = "none";
  });
  const target = document.getElementById(id);
  if (target) target.style.display = "flex";
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

async function apiGuiStart(subjectId, stageName) {
  if (!state.guiConnected) return false;
  try {
    const res = await fetch("/api/gui/start_stage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject_id: subjectId, stage_name: stageName }),
    });
    const data = await res.json();
    return data.status === "ok";
  } catch (e) {
    console.warn("apiGuiStart failed:", e);
    return false;
  }
}

async function apiGuiStop() {
  if (!state.guiConnected) return false;
  try {
    const res = await fetch("/api/gui/stop", { method: "POST" });
    const data = await res.json();
    return data.status === "ok";
  } catch (e) {
    console.warn("apiGuiStop failed:", e);
    return false;
  }
}

async function startExperimentSession() {
  try {
    const res = await fetch("/api/experiment/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subject_id: state.subjectId,
        session: state.session,
      }),
    });
    const data = await res.json();
    state.csvPath = data.csv_path;
  } catch (e) {
    console.warn("startExperimentSession failed:", e);
  }
}

// ================================ Keyboard ================================

let _keyQueue = [];

function onKeyDown(e) {
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

        // Start experiment session (creates CSV)
        await startExperimentSession();

        await apiLog({
          row_type: "experiment",
          event: "experiment_start",
          condition: "experiment",
          time_global: performance.now() / 1000,
          condition_order: "control->stress",
        });

        resolve();
      }
      if (e.key === "Escape") {
        state.aborted = true;
        document.removeEventListener("keydown", onEnter);
        resolve();
      }
    }
    document.addEventListener("keydown", onEnter);
  });
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
    `<p>${instruction}</p><br><p class="muted">本阶段时长：${fmtTime(duration)}</p>`;
  document.querySelector("#screen-instructions .card-header").className =
    "card-header accent-blue";
  document.querySelector("#screen-instructions .card-footer .hint").innerHTML =
    "按 <kbd>空格</kbd> 继续；按 <kbd>S</kbd> 跳过";

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

  // Start GUI recording
  await apiGuiStart(state.subjectId, stage);

  await apiLog({
    row_type: "block", stage, condition: stage,
    event: "block_start", skipped: false,
    time_global: performance.now() / 1000,
  });

  // Show rest screen
  showScreen("screen-rest");
  document.getElementById("rest-stage-title").textContent = title;
  document.getElementById("rest-instruction").textContent = instruction;
  document.getElementById("rest-fixation").style.display = showFixation ? "block" : "none";

  const startTime = performance.now();
  state.skipPressed = false;

  return new Promise((resolve) => {
    function frame() {
      if (state.aborted) {
        apiGuiStop();
        resolve({ skipped: false });
        return;
      }

      const elapsed = (performance.now() - startTime) / 1000;
      const remaining = duration - elapsed;
      const progress = Math.min(elapsed / duration, 1.0);

      // Update UI
      document.getElementById("rest-countdown").textContent = fmtTime(remaining);
      document.getElementById("rest-progress").style.width = (progress * 100) + "%";
      document.getElementById("rest-timer").textContent = fmtTime(remaining);

      // Check keys
      const keys = getKeys();
      if (checkAbort(keys)) {
        apiGuiStop();
        resolve({ skipped: false });
        return;
      }
      if (checkSkip(keys)) {
        apiGuiStop();
        apiLog({
          row_type: "block", stage, condition: stage,
          event: "block_end_skipped", skipped: true,
          time_global: performance.now() / 1000,
          duration: elapsed,
        });
        resolve({ skipped: true });
        return;
      }

      if (elapsed >= duration) {
        // Block finished normally
        apiGuiStop();
        apiLog({
          row_type: "block", stage, condition: stage,
          event: "block_end", skipped: false,
          time_global: performance.now() / 1000,
          duration: elapsed,
        });
        resolve({ skipped: false });
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

  // Start GUI recording
  await apiGuiStart(state.subjectId, condition);

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
      apiGuiStop();
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
      if (fixationKeys === "Escape") { state.aborted = true; apiGuiStop(); break; }
      if (checkSkip([fixationKeys])) { skipped = true; break; }
    }

    if (state.aborted) { apiGuiStop(); break; }
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

    if (state.aborted) { apiGuiStop(); break; }
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
      if (feedbackKeys === "Escape") { state.aborted = true; apiGuiStop(); break; }
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

    if (state.aborted) { apiGuiStop(); break; }
    if (skipped) break;

    // ---- ITI ----
    showScreen("screen-math");
    document.getElementById("math-expression").textContent = "";
    document.getElementById("math-answer").textContent = "";
    const itiDuration = randRange(config.iti_min, config.iti_max);
    const itiKeys = await waitForKey(
      ["Escape", SKIP_KEY, SKIP_KEY_UPPER],
      itiDuration
    );
    if (itiKeys) {
      if (itiKeys === "Escape") { state.aborted = true; apiGuiStop(); break; }
      if (checkSkip([itiKeys])) { skipped = true; break; }
    }
  }

  apiGuiStop();

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
    state.guiConnected = state.config.gui_connected;
  } catch (e) {
    console.warn("Failed to load config:", e);
    state.config = {};
  }

  console.log("GUI Connected:", state.guiConnected);

  try {
    // 1. Subject Info
    await runSubjectInfo();
    if (state.aborted) { await runAbortScreen(); return; }

    // 2. Instructions
    await runInstructions();
    if (state.aborted) { await runAbortScreen(); return; }

    // 3. Eyes Open
    let result = await runRestBlock("eyes_open", "睁眼静息", "请睁眼注视屏幕中央，保持放松。", true);
    if (state.aborted) { await runAbortScreen(); return; }
    await runVAS("eyes_open");
    if (state.aborted) { await runAbortScreen(); return; }

    // 4. Eyes Closed
    result = await runRestBlock("eyes_closed", "闭眼静息", "请闭上眼睛，保持清醒和放松。听到提示后再睁眼。", false);
    if (state.aborted) { await runAbortScreen(); return; }
    await runVAS("eyes_closed");
    if (state.aborted) { await runAbortScreen(); return; }

    // 5. Practice
    const practiceSummary = await runMathBlock("practice", "练习阶段");
    if (state.aborted) { await runAbortScreen(); return; }
    await runVAS("practice");
    if (state.aborted) { await runAbortScreen(); return; }

    // 6. Control
    const controlSummary = await runMathBlock("control", "Control Math");
    if (state.aborted) { await runAbortScreen(); return; }
    await runVAS("control");
    if (state.aborted) { await runAbortScreen(); return; }

    // 7. Stress — derive targets from control performance
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

    // 8. Recovery
    result = await runRestBlock("recovery", "Recovery", "请安静休息，尽量放松。", false);
    if (state.aborted) { await runAbortScreen(); return; }
    await runVAS("recovery");
    if (state.aborted) { await runAbortScreen(); return; }

    // 9. Experiment End
    await apiLog({
      row_type: "experiment",
      event: "experiment_end",
      condition: "experiment",
      time_global: performance.now() / 1000,
    });

    await runEndScreen();

  } finally {
    // Ensure GUI is stopped
    await apiGuiStop();
  }
}

// ================================ Start ================================

main().catch((err) => {
  console.error("Experiment crashed:", err);
  apiGuiStop();
});
