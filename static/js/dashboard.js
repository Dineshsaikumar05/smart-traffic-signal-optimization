/**
 * dashboard.js - Real-Time Dashboard & Traffic Signal Controller
 *
 * Manages live clock, real-time 4-way traffic signal state machine (Green/Yellow/Red),
 * Chart.js density & timing visualizations, API polling (/api/status),
 * user file uploads (/api/upload), simulation runs with lighting conditions (/api/simulate),
 * night-mode theme switching, side-by-side feed comparison toggles,
 * detection accuracy pipeline telemetry, emergency vehicle simulation,
 * performance summary panel, and dashboard reset functionality.
 */

// Global State
let currentTrafficState = null;
let vehiclesChart = null;
let timingsChart = null;
let historyReductionChart = null;
let historyCountsChart = null;
let isPolling = true;
let isSubmitting = false;
let loggedMessageSet = new Set();

// Real-Time Signal Timing State Machine
let signalCycle = {
    order: ["east", "north", "south", "west"],
    currentIndex: 0,
    currentPhase: "green", // "green" or "yellow"
    remainingSeconds: 30,
    timerInterval: null
};

document.addEventListener("DOMContentLoaded", () => {
    initClock();
    initCharts();
    initHistoryCharts();
    setupEventListeners();
    fetchInitialStatus();
    fetchRunHistory();
    startPolling();
});

/* ==========================================================================
   1. Live Clock
   ========================================================================== */
function initClock() {
    const clockEl = document.getElementById("liveClock");
    function updateClock() {
        const now = new Date();
        if (clockEl) {
            clockEl.textContent = now.toTimeString().split(" ")[0];
        }
    }
    updateClock();
    setInterval(updateClock, 1000);
}

/* ==========================================================================
   2. Chart.js Visualizations
   ========================================================================== */
function initCharts() {
    const ctxVehicles = document.getElementById("vehiclesChart");
    const ctxTimings = document.getElementById("timingsChart");

    if (ctxVehicles) {
        vehiclesChart = new Chart(ctxVehicles, {
            type: "bar",
            data: {
                labels: ["North", "South", "East", "West"],
                datasets: [{
                    label: "Vehicles Detected",
                    data: [0, 0, 0, 0],
                    backgroundColor: [
                        "rgba(0, 229, 255, 0.7)",
                        "rgba(59, 130, 246, 0.7)",
                        "rgba(255, 51, 102, 0.7)",
                        "rgba(255, 184, 0, 0.7)"
                    ],
                    borderColor: [
                        "#00e5ff",
                        "#3b82f6",
                        "#ff3366",
                        "#ffb800"
                    ],
                    borderWidth: 1.5,
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: "#121826",
                        titleColor: "#f0f4fc",
                        bodyColor: "#94a3b8",
                        borderColor: "rgba(255,255,255,0.1)",
                        borderWidth: 1
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: "rgba(255, 255, 255, 0.05)" },
                        ticks: { color: "#64748b", font: { family: "JetBrains Mono" } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: "#94a3b8", font: { family: "Inter", weight: 600 } }
                    }
                }
            }
        });
    }

    if (ctxTimings) {
        // max_green is 60s, so max = max_green + 10 = 70 with stepSize 10
        timingsChart = new Chart(ctxTimings, {
            type: "bar",
            data: {
                labels: ["North", "South", "East", "West"],
                datasets: [
                    {
                        label: "Adaptive Green (s)",
                        data: [0, 0, 0, 0],
                        backgroundColor: "rgba(0, 242, 152, 0.75)",
                        borderColor: "#00f298",
                        borderWidth: 1.5,
                        borderRadius: 6
                    },
                    {
                        label: "Fixed Baseline 30s",
                        data: [30, 30, 30, 30],
                        backgroundColor: "rgba(100, 116, 139, 0.35)",
                        borderColor: "#64748b",
                        borderWidth: 1,
                        borderRadius: 6
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "top",
                        align: "center",
                        labels: {
                            color: "#94a3b8",
                            font: { size: 11, family: "Inter" },
                            boxWidth: 14,
                            padding: 10
                        }
                    },
                    tooltip: {
                        backgroundColor: "#121826",
                        titleColor: "#f0f4fc",
                        bodyColor: "#94a3b8",
                        borderColor: "rgba(255,255,255,0.1)",
                        borderWidth: 1
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        min: 0,
                        max: 70, // max_green (60) + 10
                        grid: { color: "rgba(255, 255, 255, 0.05)" },
                        ticks: {
                            stepSize: 10,
                            color: "#64748b",
                            font: { family: "JetBrains Mono" }
                        }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: "#94a3b8", font: { family: "Inter", weight: 600 } }
                    }
                }
            }
        });
    }
}

function updateCharts(roadsData) {
    if (!roadsData) return;
    const roads = ["north", "south", "east", "west"];
    const vehicleCounts = roads.map(r => roadsData[r]?.count || 0);
    const greenTimes = roads.map(r => roadsData[r]?.green_time || 0);

    if (vehiclesChart) {
        vehiclesChart.data.datasets[0].data = vehicleCounts;
        vehiclesChart.update();
    }

    if (timingsChart) {
        timingsChart.data.datasets[0].data = greenTimes;
        timingsChart.update();
    }
}

/* ==========================================================================
   3. Real-Time Signal Automation Engine
   ========================================================================== */
function initSignalCycle(order, roads, isReset = false) {
    if (!order || order.length === 0) return;

    if (signalCycle.timerInterval) {
        clearInterval(signalCycle.timerInterval);
        signalCycle.timerInterval = null;
    }

    signalCycle.order = [...order];
    signalCycle.currentIndex = 0;
    signalCycle.currentPhase = "green";

    const initialRoad = signalCycle.order[0];
    const initialGreen = (roads && roads[initialRoad]) ? roads[initialRoad].green_time : 30;
    signalCycle.remainingSeconds = initialGreen;

    // Display service sequence strictly matching the active running order
    updateServiceSequenceDisplay(signalCycle.order);

    if (isReset) {
        logEvent("SIGNAL", "Traffic Cycle restarted after reset.");
    } else {
        logEvent("SIGNAL", `Traffic Cycle started: Active approach is [${initialRoad.toUpperCase()}] for ${initialGreen}s.`);
    }

    renderSignalState(roads);

    signalCycle.timerInterval = setInterval(() => {
        tickSignalTimer();
    }, 1000);
}

function updateServiceSequenceDisplay(order) {
    const seqEl = document.getElementById("serviceOrderSequence");
    if (seqEl && order && order.length > 0) {
        seqEl.innerHTML = order.map(r => r.toUpperCase()).join(" &rarr; ");
    }
}

function tickSignalTimer() {
    if (!currentTrafficState || !currentTrafficState.roads) return;

    signalCycle.remainingSeconds--;

    const currentRoad = signalCycle.order[signalCycle.currentIndex];

    // Guard: if new data arrived and invalidated currentRoad, restart cycle cleanly
    if (!currentTrafficState.roads[currentRoad]) {
        if (currentTrafficState.order && currentTrafficState.roads) {
            initSignalCycle(currentTrafficState.order, currentTrafficState.roads);
        }
        return;
    }

    // Transition to Yellow at 3 seconds remaining
    if (signalCycle.remainingSeconds === 3 && signalCycle.currentPhase === "green") {
        signalCycle.currentPhase = "yellow";
        logEvent("SIGNAL", `⚠️ Approach [${currentRoad.toUpperCase()}] entered YELLOW clearance phase (3s warning).`);
    }

    // Phase complete: switch to next road in order of service
    if (signalCycle.remainingSeconds <= 0) {
        // Check if emergency was active: when emergency priority road finishes or cycle completes
        if (currentTrafficState && currentTrafficState.emergency_road) {
            const emergRoad = currentTrafficState.emergency_road;
            if (currentRoad === emergRoad || signalCycle.currentIndex >= (signalCycle.order.length - 1)) {
                clearEmergencySimulation(true, "expired");
                return;
            }
        }

        signalCycle.currentIndex = signalCycle.currentIndex + 1;

        // If cycle finished (served all roads in sequence):
        if (signalCycle.currentIndex >= signalCycle.order.length) {
            // Start fresh cycle with latest order from currentTrafficState
            signalCycle.order = [...(currentTrafficState.order || signalCycle.order)];
            signalCycle.currentIndex = 0;
            updateServiceSequenceDisplay(signalCycle.order);
        }

        signalCycle.currentPhase = "green";

        const nextRoad = signalCycle.order[signalCycle.currentIndex];
        const nextGreen = currentTrafficState.roads[nextRoad]?.green_time || 30;
        signalCycle.remainingSeconds = nextGreen;

        const count = currentTrafficState.roads[nextRoad]?.count || 0;
        const density = currentTrafficState.roads[nextRoad]?.density || "Normal";
        logEvent("SIGNAL", `🟢 Signal turned GREEN for [${nextRoad.toUpperCase()}] (${nextGreen}s allocated | ${density} Density: ${count} veh).`);
    }

    renderSignalState(currentTrafficState.roads);
}

function renderSignalState(roads) {
    if (!roads) return;
    const allRoads = ["north", "south", "east", "west"];
    const activeRoad = signalCycle.order[signalCycle.currentIndex];
    const phase = signalCycle.currentPhase; // "green" or "yellow"

    allRoads.forEach(road => {
        const bulbRed = document.getElementById(`bulb${capitalize(road)}Red`);
        const bulbYellow = document.getElementById(`bulb${capitalize(road)}Yellow`);
        const bulbGreen = document.getElementById(`bulb${capitalize(road)}Green`);
        const countdown = document.getElementById(`countdown${capitalize(road)}`);

        if (road === activeRoad) {
            if (phase === "green") {
                bulbRed?.classList.remove("active");
                bulbYellow?.classList.remove("active");
                bulbGreen?.classList.add("active");
            } else { // yellow
                bulbRed?.classList.remove("active");
                bulbYellow?.classList.add("active");
                bulbGreen?.classList.remove("active");
            }

            if (countdown) {
                countdown.textContent = `${signalCycle.remainingSeconds}s`;
                countdown.classList.add("active");
            }
        } else {
            // Non-active roads stay solid RED
            bulbRed?.classList.add("active");
            bulbYellow?.classList.remove("active");
            bulbGreen?.classList.remove("active");

            if (countdown) {
                countdown.textContent = "--";
                countdown.classList.remove("active");
            }
        }
    });

    // Update Center Intersection HUD
    const centerRoadName = document.getElementById("centerActiveRoadName");
    const centerTimer = document.getElementById("centerActiveTimer");

    if (centerRoadName) {
        centerRoadName.textContent = activeRoad ? activeRoad.toUpperCase() : "--";
        centerRoadName.style.color = phase === "yellow" ? "var(--accent-yellow)" : "var(--text-primary)";
    }
    if (centerTimer) {
        centerTimer.textContent = `${signalCycle.remainingSeconds}s`;
        centerTimer.style.color = phase === "yellow" ? "var(--accent-yellow)" : "var(--accent-green)";
    }

    // Update Signal Phase Timeline
    if (currentTrafficState && currentTrafficState.roads) {
        updateSignalTimeline(signalCycle.order, currentTrafficState.roads, activeRoad, signalCycle.remainingSeconds);
    }
}

/* ==========================================================================
   3a. Signal Phase Timeline
   ========================================================================== */
function updateSignalTimeline(order, roads, activeRoad, remainingSeconds) {
    const bar = document.getElementById("signalTimelineBar");
    const infoEl = document.getElementById("timelineActiveInfo");
    if (!bar || !order || !roads) return;

    const cycleTotalSec = order.reduce((sum, r) => sum + (roads[r]?.green_time || 0), 0) || 120;

    // Rebuild segments if order changed (compare current segment count)
    const existingSegments = bar.querySelectorAll(".timeline-segment");
    const needsRebuild = existingSegments.length !== order.length ||
        [...existingSegments].some((el, i) => el.dataset.road !== order[i]);

    if (needsRebuild) {
        bar.innerHTML = "";
        order.forEach(road => {
            const green = roads[road]?.green_time || 0;
            const widthPct = cycleTotalSec > 0 ? (green / cycleTotalSec * 100).toFixed(1) : 25;

            const seg = document.createElement("div");
            seg.className = `timeline-segment seg-${road}`;
            seg.dataset.road = road;
            seg.style.flex = `0 0 ${widthPct}%`;
            seg.title = `${road.toUpperCase()}: ${green}s`;

            const progress = document.createElement("div");
            progress.className = "timeline-segment-progress";
            progress.style.width = "0%";

            const label = document.createElement("span");
            label.className = "timeline-segment-label";
            label.textContent = road.substring(0, 1).toUpperCase();

            seg.appendChild(progress);
            seg.appendChild(label);
            bar.appendChild(seg);
        });
    }

    // Update active state and progress fill
    const segments = bar.querySelectorAll(".timeline-segment");
    segments.forEach(seg => {
        const road = seg.dataset.road;
        const progress = seg.querySelector(".timeline-segment-progress");
        const isActive = road === activeRoad;

        if (isActive) {
            seg.classList.add("active-segment");
            const green = roads[road]?.green_time || 1;
            const elapsed = green - remainingSeconds;
            const progressPct = Math.min(100, Math.max(0, (elapsed / green) * 100)).toFixed(1);
            if (progress) progress.style.width = `${progressPct}%`;
        } else {
            seg.classList.remove("active-segment");
            if (progress) progress.style.width = "0%";
        }
    });

    // Update info label: "Active: NORTH, 46s left of 54s"
    if (infoEl && activeRoad) {
        const green = roads[activeRoad]?.green_time || 0;
        infoEl.textContent = `Active: ${activeRoad.toUpperCase()}, ${remainingSeconds}s left of ${green}s`;
    }
}

/* ==========================================================================
   4. UI Updating & Rendering (Night Mode, Emergency, Badges, Telemetry)
   ========================================================================== */
function updateDashboardUI(data) {
    if (!data || !data.roads) return;

    currentTrafficState = data;

    // 0. Waiting for Photos Banner (Requirement A2)
    const waitingNotice = document.getElementById("waitingNotice");
    if (waitingNotice) {
        if (!data.has_analyzed_data && !data.is_test_data) {
            waitingNotice.style.display = "flex";
        } else {
            waitingNotice.style.display = "none";
        }
    }

    // 0b. Emergency Buttons enabling/disabling (Requirement A5: Disabled with tooltip until first Analyze)
    const canEmergency = !!data.has_analyzed_data;
    ["North", "South", "East", "West"].forEach(dir => {
        const btn = document.getElementById(`btnEmerg${dir}`);
        if (btn) {
            btn.disabled = !canEmergency;
            if (!canEmergency) {
                btn.title = "Analyze traffic first";
                btn.classList.add("disabled-btn");
            } else {
                btn.title = `Trigger emergency override for ${dir} approach`;
                btn.classList.remove("disabled-btn");
            }
        }
    });

    // 1. Night Mode Variant Theme & Banner Switching
    const nightBanner = document.getElementById("nightModeBanner");
    const isNight = !!data.is_night_mode;

    if (isNight) {
        document.body.classList.add("night-mode-active");
        if (nightBanner) nightBanner.style.display = "block";
    } else {
        document.body.classList.remove("night-mode-active");
        if (nightBanner) nightBanner.style.display = "none";
    }

    // 1b. Emergency Priority Banner and Status Tag
    const emergBanner = document.getElementById("emergencyAlertBanner");
    const emergTitle = document.getElementById("emergencyAlertTitle");
    const emergDesc = document.getElementById("emergencyAlertDesc");
    const emergStatusTag = document.getElementById("emergencyStatusTag");
    const btnClearEmerg = document.getElementById("btnClearEmergency");
    const emergencyRoad = data.emergency_road || null;

    if (emergencyRoad) {
        if (emergBanner) emergBanner.style.display = "block";
        if (emergTitle) emergTitle.textContent = `EMERGENCY PRIORITY ACTIVE: ${emergencyRoad.toUpperCase()} APPROACH`;
        if (emergDesc) emergDesc.textContent = `Immediate priority green (60s) allocated. Remaining roads share 60s by density. Measured vehicle counts strictly preserved.`;
        if (emergStatusTag) {
            emergStatusTag.textContent = `PRIORITY: ${emergencyRoad.toUpperCase()}`;
            emergStatusTag.classList.add("active");
        }
        if (btnClearEmerg) btnClearEmerg.style.display = "inline-flex";
    } else {
        if (emergBanner) emergBanner.style.display = "none";
        if (emergStatusTag) {
            emergStatusTag.textContent = "STANDBY";
            emergStatusTag.classList.remove("active");
        }
        if (btnClearEmerg) btnClearEmerg.style.display = "none";
    }

    // 2. Header info & Current Mode
    const headerCycle = document.getElementById("headerCycleTime");
    const modeIndicator = document.getElementById("modeName");
    const modeExplainer = document.getElementById("modeExplainer");
    const lastSync = document.getElementById("lastSyncTime");

    if (headerCycle) {
        if (data.unallocated_seconds && data.unallocated_seconds > 0) {
            headerCycle.textContent = `${data.actual_cycle_time || 90}s (partial data, ${data.unallocated_seconds}s unallocated)`;
            headerCycle.title = `${data.cycle_label || 'Partial data'} - ${data.unallocated_seconds}s unallocated`;
        } else {
            headerCycle.textContent = `${data.actual_cycle_time || data.cycle_time || 120}s`;
            headerCycle.title = "";
        }
    }
    if (modeIndicator) {
        let m = data.mode || "Default fixed timer (no data yet)";
        if (data.emergency_road) {
            m = `Emergency (${data.emergency_road.toUpperCase()})`;
        } else if (data.is_test_data) {
            m = "Test (random data)";
        } else if (data.underlying_mode) {
            m = data.underlying_mode;
            if (data.mode && data.mode.startsWith("Upload")) {
                m = data.mode;
            }
        }
        modeIndicator.textContent = m;

        if (modeExplainer) {
            if (data.emergency_road) {
                modeExplainer.textContent = "(Priority override active on emergency corridor)";
            } else if (data.is_test_data) {
                modeExplainer.textContent = "(Random test data generated for evaluation)";
            } else if (!data.has_analyzed_data) {
                modeExplainer.textContent = "(Equal fixed plan running - upload photos to enable adaptive control)";
            } else {
                modeExplainer.textContent = "(Real camera feeds processed with YOLOv8)";
            }
        }
    }

    if (lastSync) lastSync.textContent = `Last synchronized: ${data.timestamp || new Date().toLocaleTimeString()}`;

    // 3. Render Four Road Cards with Lighting Badges & Dual Feed URLs
    const roads = ["north", "south", "east", "west"];
    let nightCorridorCount = 0;
    let duskCorridorCount = 0;

    const confSlider = document.getElementById("confSlider");
    const confVal = confSlider ? Number(confSlider.value).toFixed(2) : "0.30";

    roads.forEach(road => {
        const rData = data.roads[road];
        if (!rData) return;
        const cap = capitalize(road);

        const countEl = document.getElementById(`countVal${cap}`);
        const greenEl = document.getElementById(`greenVal${cap}`);
        const shareEl = document.getElementById(`shareVal${cap}`);
        const badgeEl = document.getElementById(`densityBadge${cap}`);
        const lightBadge = document.getElementById(`lightingBadge${cap}`);
        const lightText = document.getElementById(`lightingText${cap}`);
        const emergBadge = document.getElementById(`emergBadge${cap}`);
        const sampleBadge = document.getElementById(`sampleBadge${cap}`);
        const engineBadge = document.getElementById(`engineBadge${cap}`);
        const videoStats = document.getElementById(`videoStats${cap}`);
        const videoAvg = document.getElementById(`videoAvg${cap}`);
        const videoMax = document.getElementById(`videoMax${cap}`);
        const roadCard = document.getElementById(`card${cap}`);

        const testDataBadge = document.getElementById(`testDataBadge${cap}`);
        const prevBadge = document.getElementById(`previousBadge${cap}`);
        const noDataBadge = document.getElementById(`noDataBadge${cap}`);
        const dupBanner = document.getElementById(`duplicateNote${cap}`);
        const failBanner = document.getElementById(`uploadFailed${cap}`);

        // Count display: "—" if count is null or undefined
        if (countEl) {
            countEl.textContent = (rData.count !== null && rData.count !== undefined) ? rData.count : "—";
        }
        if (greenEl) greenEl.textContent = `${rData.green_time}s`;
        if (shareEl) {
            shareEl.textContent = (rData.share_pct !== null && rData.share_pct !== undefined && rData.count !== null) ? `${rData.share_pct}%` : "—";
        }

        // Density badge
        if (badgeEl) {
            if (rData.is_no_data || rData.count === null) {
                badgeEl.textContent = "NO DATA";
                badgeEl.className = "density-badge badge-nodata";
            } else {
                badgeEl.textContent = rData.density || "LOW";
                badgeEl.className = `density-badge badge-${(rData.density || "low").toLowerCase()}`;
            }
        }

        // Status tags
        if (testDataBadge) {
            testDataBadge.style.display = (rData.is_test_data || data.is_test_data) ? "inline-block" : "none";
        }
        if (prevBadge) {
            prevBadge.style.display = rData.is_previous ? "inline-block" : "none";
        }
        if (noDataBadge) {
            noDataBadge.style.display = (rData.is_no_data || rData.count === null) ? "inline-block" : "none";
        }

        // Duplicate note
        if (dupBanner) {
            if (rData.is_duplicate || rData.duplicate_of) {
                dupBanner.style.display = "block";
                dupBanner.textContent = `⚠️ Same file as ${rData.duplicate_of ? capitalize(rData.duplicate_of) : "another"} corridor`;
            } else {
                dupBanner.style.display = "none";
            }
        }

        // Upload failure banner
        if (failBanner) {
            if (rData.upload_failed || rData.error) {
                failBanner.style.display = "block";
                failBanner.textContent = `❌ Upload failed: ${rData.error || "Could not decode media"}`;
            } else {
                failBanner.style.display = "none";
            }
        }

        // Engine badge on road card — derived strictly from data_source
        if (engineBadge) {
            const ds = rData.data_source || data.data_source || "sample";
            if (rData.is_test_data || data.is_test_data || ds === "simulation") {
                engineBadge.textContent = "Engine: Simulated (TEST DATA)";
            } else if (rData.is_previous) {
                engineBadge.textContent = "Engine: Previous analysis";
            } else if (rData.is_no_data || rData.count === null) {
                engineBadge.textContent = "Engine: Default fixed timer";
            } else if (ds === "sample" || rData.is_sample) {
                engineBadge.textContent = "Engine: Sample images";
            } else {
                let eng = rData.engine || "YOLOv8n";
                if (eng.toLowerCase().includes("opencv")) {
                    eng = "OpenCV fallback";
                }
                const confStr = rData.conf_threshold != null ? Number(rData.conf_threshold).toFixed(2) : confVal;
                engineBadge.textContent = `Engine: ${eng} (conf ${confStr})`;
            }
        }

        // Sample badge on road card
        if (sampleBadge) {
            sampleBadge.style.display = (rData.is_sample && !data.is_test_data) ? "inline-block" : "none";
        }

        // Video stats on road card
        if (videoStats) {
            if (rData.is_video && rData.video_avg_count != null) {
                videoStats.style.display = "block";
                if (videoAvg) videoAvg.textContent = rData.video_avg_count;
                if (videoMax) videoMax.textContent = rData.video_max_count;
            } else {
                videoStats.style.display = "none";
            }
        }

        // Emergency badge on road card
        const isThisEmerg = (road === emergencyRoad);
        if (emergBadge) {
            emergBadge.style.display = isThisEmerg ? "inline-block" : "none";
        }
        if (roadCard) {
            if (isThisEmerg) roadCard.classList.add("is-emergency");
            else roadCard.classList.remove("is-emergency");
        }

        // Lighting Badge per road
        const lMode = rData.lighting_mode || "day";
        const brightness = rData.brightness != null ? Math.round(rData.brightness) : "--";

        if (lMode === "night") nightCorridorCount++;
        if (lMode === "dusk") duskCorridorCount++;

        if (lightBadge && lightText) {
            lightBadge.className = `lighting-badge lighting-${lMode}`;
            let icon = "☀️";
            let label = "Day";
            if (lMode === "dusk") {
                icon = "🌆";
                label = "Dusk";
            } else if (lMode === "night") {
                icon = "🌙";
                label = "Night";
            }
            lightBadge.innerHTML = `<span class="badge-icon">${icon}</span> <span class="badge-text" id="lightingText${cap}">${label} (${brightness})</span>`;
        }

        // Feed Images
        const ts = Date.now();
        const mainUrl = rData.image_url ? `${rData.image_url.split("?")[0]}?t=${ts}` : "";
        const origUrl = rData.original_image_url ? `${rData.original_image_url.split("?")[0]}?t=${ts}` : mainUrl;
        const enhUrl = rData.enhanced_image_url ? `${rData.enhanced_image_url.split("?")[0]}?t=${ts}` : mainUrl;

        const imgSingle = document.getElementById(`img${cap}`);
        const imgOrig = document.getElementById(`img${cap}Orig`);
        const imgEnh = document.getElementById(`img${cap}Enh`);
        const btnToggle = document.getElementById(`btnToggle${cap}`);

        if (imgSingle && mainUrl) imgSingle.src = mainUrl;
        if (imgOrig && origUrl) imgOrig.src = origUrl;
        if (imgEnh && enhUrl) imgEnh.src = enhUrl;

        if (btnToggle) {
            if (lMode === "night") {
                btnToggle.classList.add("highlight-night");
            } else {
                btnToggle.classList.remove("highlight-night");
            }
        }

        // Accuracy Telemetry
        const accLight = document.getElementById(`accLighting${cap}`);
        const accPipe = document.getElementById(`accPipeline${cap}`);
        const accBrightVal = document.getElementById(`accBrightVal${cap}`);
        const accMeter = document.getElementById(`accMeter${cap}`);
        const accDesc = document.getElementById(`accDesc${cap}`);

        if (accLight) {
            let tagText = "☀️ DAY";
            if (lMode === "dusk") tagText = "🌆 DUSK";
            else if (lMode === "night") tagText = "🌙 NIGHT";
            accLight.textContent = tagText;
            accLight.className = `acc-lighting-tag tag-${lMode}`;
        }

        const ds = rData.data_source || data.data_source || "sample";
        if (accPipe) {
            if (rData.is_test_data || data.is_test_data || ds === "simulation") {
                accPipe.textContent = "Simulated counts (no detection run - TEST DATA)";
            } else if (rData.is_no_data || rData.count === null) {
                accPipe.textContent = "No media uploaded (default fixed allocation)";
            } else if (rData.is_previous) {
                accPipe.textContent = "Previous analysis retained";
            } else if (ds === "sample" || rData.is_sample) {
                accPipe.textContent = "Sample Benchmark Feed (no live detection)";
            } else {
                let eng = rData.engine || "YOLOv8n";
                if (eng.toLowerCase().includes("opencv")) eng = "OpenCV fallback";
                const confStr = rData.conf_threshold != null ? Number(rData.conf_threshold).toFixed(2) : confVal;
                accPipe.textContent = `${rData.pipeline || "Standard Vision Pipeline"} (${eng}, conf ${confStr})`;
            }
        }

        if (accBrightVal) {
            accBrightVal.textContent = brightness;
        }

        if (accMeter) {
            const meterPct = Math.min(100, Math.max(8, Math.round((Number(brightness) / 255.0) * 100)));
            accMeter.style.width = `${meterPct}%`;
            accMeter.className = `acc-meter-fill meter-${lMode}`;
        }

        if (accDesc) {
            if (rData.is_test_data || data.is_test_data || ds === "simulation") {
                accDesc.textContent = "Simulated counts (no detection run - TEST DATA)";
            } else if (rData.is_no_data || rData.count === null) {
                accDesc.textContent = "Approach is awaiting camera feed upload. Operating on fixed timer.";
            } else if (rData.is_previous) {
                accDesc.textContent = "Retaining count from prior analysis run.";
            } else if (ds === "sample" || rData.is_sample) {
                accDesc.textContent = "Pre-computed baseline benchmark image — camera feeds not currently uploaded.";
            } else {
                let eng = rData.engine || "YOLOv8n";
                if (eng.toLowerCase().includes("opencv")) eng = "OpenCV fallback";
                const confStr = rData.conf_threshold != null ? Number(rData.conf_threshold).toFixed(2) : confVal;
                if (lMode === "night") {
                    accDesc.textContent = `Night scene: LAB CLAHE & adaptive gamma boost shadow details + dual-headlight pairing / motorcycle detection. Engine: ${eng} (conf ${confStr}).`;
                } else if (lMode === "dusk") {
                    accDesc.textContent = `Dusk low-light: Adaptive gamma & CLAHE applied to amplify vehicle contrast against dim pavement. Engine: ${eng} (conf ${confStr}).`;
                } else {
                    accDesc.textContent = `Daylight scene: ${eng} detection, conf=${confStr}, COCO vehicle classes (car, motorcycle, bus, truck).`;
                }
            }
        }
    });

    // 3b. Upload warning banners (0 or 1 vehicles detected on uploaded images)
    const isUploadMode = (data.mode || "").toLowerCase().includes("upload") || data.data_source === "upload";
    roads.forEach(road => {
        const warnEl = document.getElementById(`uploadWarning${capitalize(road)}`);
        if (!warnEl) return;
        const rData = data.roads[road];
        if (!rData) { warnEl.style.display = "none"; return; }
        if (isUploadMode && !rData.is_sample && !rData.is_previous && !rData.is_no_data && rData.count !== null && rData.count <= 1) {
            warnEl.style.display = "block";
        } else {
            warnEl.style.display = "none";
        }
    });

    // 3c. Ground truth actual count feedback on card & Accuracy Report panel
    roads.forEach(road => {
        const feedbackEl = document.getElementById(`accuracyFeedback${capitalize(road)}`);
        const rData = data.roads[road];
        if (!feedbackEl || !rData) return;

        if (rData.accuracy_feedback && rData.accuracy_feedback !== "n/a (not analyzed)") {
            feedbackEl.textContent = `🎯 ${rData.accuracy_feedback}`;
            feedbackEl.style.display = "block";
        } else {
            feedbackEl.style.display = "none";
        }
    });

    const accReport = data.accuracy_report || null;
    const hasReport = accReport && accReport.mae !== null;
    const maeValEl = document.getElementById("accuracyMaeVal");
    const reportPlaceholder = document.getElementById("accuracyReportPlaceholder");
    const reportWrapper = document.getElementById("accuracyReportWrapper");
    const reportTbody = document.getElementById("accuracyReportTableBody");

    if (maeValEl) {
        maeValEl.textContent = hasReport ? `${accReport.mae} veh (MPE: ${accReport.mpe || 0}%)` : "--";
    }

    if (accReport && accReport.per_road && reportWrapper && reportTbody) {
        const rowsToRender = roads.map(road => {
            const item = accReport.per_road?.[road];
            if (!item) return "";
            if (!item.analyzed) {
                return `
                    <tr class="row-not-analyzed">
                        <td><strong>${capitalize(road)} Approach</strong></td>
                        <td class="font-mono">${item.detected !== null ? item.detected + " veh" : "—"}</td>
                        <td class="font-mono text-muted">${item.actual !== null ? item.actual + " veh" : "—"}</td>
                        <td class="font-mono text-muted">—</td>
                        <td class="font-mono text-muted">n/a (not analyzed)</td>
                        <td><span class="badge-acc-na">Not Analyzed</span></td>
                    </tr>
                `;
            }
            if (item.actual === null) {
                return `
                    <tr>
                        <td><strong>${capitalize(road)} Approach</strong></td>
                        <td class="font-mono">${item.detected} veh</td>
                        <td class="font-mono text-muted">—</td>
                        <td class="font-mono text-muted">—</td>
                        <td class="font-mono text-muted">—</td>
                        <td><span class="badge-acc-na">No Ground Truth</span></td>
                    </tr>
                `;
            }
            const errBadge = item.error_pct <= 10.0 
                ? `<span class="badge-acc-high">High Accuracy (${item.error_pct}%)</span>`
                : item.error_pct <= 25.0 
                    ? `<span class="badge-acc-med">Moderate (${item.error_pct}%)</span>`
                    : `<span class="badge-acc-dev">Deviation (${item.error_pct}%)</span>`;

            return `
                <tr>
                    <td><strong>${capitalize(road)} Approach</strong></td>
                    <td class="font-mono">${item.detected} veh</td>
                    <td class="font-mono text-blue font-bold">${item.actual} veh</td>
                    <td class="font-mono">${item.abs_error} veh</td>
                    <td class="font-mono font-bold">${item.error_pct}%</td>
                    <td>${errBadge}</td>
                </tr>
            `;
        }).filter(Boolean);

        if (rowsToRender.length > 0) {
            if (reportPlaceholder) reportPlaceholder.style.display = "none";
            reportWrapper.style.display = "block";
            reportTbody.innerHTML = rowsToRender.join("");
        } else {
            if (reportPlaceholder) reportPlaceholder.style.display = "block";
            if (reportWrapper) reportWrapper.style.display = "none";
        }
    } else {
        if (reportPlaceholder) reportPlaceholder.style.display = "block";
        if (reportWrapper) reportWrapper.style.display = "none";
    }

    // Accuracy Summary Pill (Requirement 6: Simulation mode shows "Simulation Mode - no detection run")
    const isSimMode = data.is_test_data || data.data_source === "simulation" || (data.mode || "").toLowerCase().includes("simulation");
    const accSummaryText = document.getElementById("accuracySummaryText");
    if (accSummaryText) {
        if (isSimMode) {
            accSummaryText.textContent = "Simulation Mode - no detection run";
        } else if (!data.has_analyzed_data) {
            accSummaryText.textContent = "Waiting for Camera Feeds (Default Fixed Plan)";
        } else if (nightCorridorCount > 0) {
            accSummaryText.textContent = `Night Vision Active (${nightCorridorCount} ${nightCorridorCount === 1 ? 'corridor' : 'corridors'})`;
        } else if (duskCorridorCount > 0) {
            accSummaryText.textContent = `Low-Light Boost Active (${duskCorridorCount} ${duskCorridorCount === 1 ? 'corridor' : 'corridors'})`;
        } else {
            accSummaryText.textContent = "Daylight Silhouette Sensors Active";
        }
    }

    // 4. Update Comparison Metrics
    if (data.comparison) {
        const comp = data.comparison;
        const fixedWaitEl = document.getElementById("valFixedWait");
        const adaptiveWaitEl = document.getElementById("valAdaptiveWait");
        const savingsBadge = document.getElementById("savingsBadge");
        const efficiencyNote = document.getElementById("adaptiveEfficiencyNote");
        const kpiFixed = document.getElementById("kpiCongestionFixed");
        const kpiAdaptive = document.getElementById("kpiCongestionAdaptive");
        const kpiRedPct = document.getElementById("kpiReductionPct");
        const progressFill = document.getElementById("efficiencyProgressBar");
        const progressLabel = document.getElementById("efficiencyPctLabel");

        if (!data.has_analyzed_data && !data.is_test_data) {
            if (fixedWaitEl) fixedWaitEl.textContent = "30.0s";
            if (adaptiveWaitEl) adaptiveWaitEl.textContent = "30.0s";
            if (savingsBadge) savingsBadge.textContent = "0.0% Less Delay";
            if (efficiencyNote) efficiencyNote.textContent = "Default Baseline Timers";
            if (kpiFixed) kpiFixed.textContent = "1.0x";
            if (kpiAdaptive) kpiAdaptive.textContent = "1.0x";
            if (kpiRedPct) kpiRedPct.textContent = "0%";
            if (progressFill) progressFill.style.width = "50%";
            if (progressLabel) progressLabel.textContent = "50% Baseline (Default)";
        } else {
            if (fixedWaitEl) fixedWaitEl.textContent = `${comp.fixed_avg_wait_sec}s`;
            if (adaptiveWaitEl) adaptiveWaitEl.textContent = `${comp.adaptive_avg_wait_sec}s`;

            if (savingsBadge) {
                const redPct = comp.wait_reduction_pct != null ? comp.wait_reduction_pct : 0.0;
                savingsBadge.textContent = `${redPct}% Less Delay`;
            }

            const diffSaved = (comp.fixed_avg_wait_sec - comp.adaptive_avg_wait_sec).toFixed(1);
            if (efficiencyNote) {
                efficiencyNote.textContent = diffSaved > 0 ? `${diffSaved}s Saved per Vehicle` : "Equalized Flow";
            }

            if (kpiFixed) kpiFixed.textContent = `${comp.congestion_index_fixed}x`;
            if (kpiAdaptive) kpiAdaptive.textContent = `${comp.congestion_index_adaptive}x`;
            if (kpiRedPct) kpiRedPct.textContent = `${comp.wait_reduction_pct}%`;

            const clearanceScore = comp.clearance_efficiency_pct != null
                ? Math.round(comp.clearance_efficiency_pct)
                : Math.min(98, Math.max(50, Math.round(50 + comp.wait_reduction_pct * 0.9)));

            if (progressFill) progressFill.style.width = `${clearanceScore}%`;
            if (progressLabel) progressLabel.textContent = `${clearanceScore}% Optimal Flow`;
        }
    }

    // 5. Inject Event Logs from Backend
    if (Array.isArray(data.logs) && data.logs.length > 0) {
        data.logs.forEach(logMsg => {
            const key = `${data.timestamp || ""}_${logMsg}`;
            if (!loggedMessageSet.has(key)) {
                loggedMessageSet.add(key);
                let badge = "AI-VISION";
                if (logMsg.includes("EMERGENCY")) badge = "EMERGENCY";
                else if (logMsg.includes("night")) badge = "LOW-LIGHT";
                else if (logMsg.includes("dusk")) badge = "LOW-LIGHT";
                else if (logMsg.includes("TEST")) badge = "TEST";
                logEvent(badge, logMsg);
            }
        });
    }

    // 6. Update Charts
    updateCharts(data.roads);

    // 7. Sync Signal Automation Sequence:
    // When new data arrives mid-cycle, restart cleanly from index 0 with the fresh order
    if (!signalCycle.timerInterval || isNewSequence(data.order, data.roads)) {
        initSignalCycle(data.order, data.roads, false);
    }

    // 7b. Update Signal Phase Timeline with fresh data
    updateSignalTimeline(signalCycle.order, data.roads, signalCycle.order[signalCycle.currentIndex], signalCycle.remainingSeconds);

    // 8. Update Performance Summary Panel
    updateSummaryPanel(data);

    // 9. Refresh Run History
    fetchRunHistory();
}

function isNewSequence(newOrder, newRoads) {
    if (!signalCycle.order || signalCycle.order.length !== newOrder.length) return true;
    for (let i = 0; i < newOrder.length; i++) {
        if (signalCycle.order[i] !== newOrder[i]) return true;
    }
    // Also check if any green times changed
    if (currentTrafficState && currentTrafficState.roads && newRoads) {
        for (const r of newOrder) {
            if (currentTrafficState.roads[r]?.green_time !== newRoads[r]?.green_time) {
                return true;
            }
        }
    }
    return false;
}

/* ==========================================================================
   4a. Performance Summary Panel
   ========================================================================== */
function updateSummaryPanel(data) {
    if (!data || !data.roads) return;

    const roads = ["north", "south", "east", "west"];
    const hasAnalyzed = !!data.has_analyzed_data;
    const isTestData = !!data.is_test_data;

    const totalEl = document.getElementById("summaryTotalVehicles");
    const avgEl = document.getElementById("summaryAvgVehicles");
    const greenEl = document.getElementById("summaryGreenTimes");
    const greenTimes = roads.map(r => data.roads[r]?.green_time || 0);

    if (greenEl) greenEl.textContent = greenTimes.join(" / ") + " s";

    if (!hasAnalyzed && !isTestData) {
        if (totalEl) totalEl.textContent = "—";
        if (avgEl) avgEl.textContent = "—";
    } else {
        const counts = roads.map(r => data.roads[r]?.count || 0);
        const totalVehicles = counts.reduce((a, b) => a + b, 0);
        const avgVehicles = counts.length > 0 ? (totalVehicles / counts.length).toFixed(1) : "0.0";
        if (totalEl) totalEl.textContent = totalVehicles;
        if (avgEl) avgEl.textContent = avgVehicles;
    }

    const summaryWaitBadge = document.getElementById("summaryWaitReductionBadge");
    const waitReductEl = document.getElementById("summaryWaitReduction");
    const fixedWaitEl = document.getElementById("summaryFixedWait");
    const adaptiveWaitEl = document.getElementById("summaryAdaptiveWait");

    if (data.comparison && (hasAnalyzed || isTestData)) {
        const comp = data.comparison;
        const val = comp.wait_reduction_pct;
        const formattedVal = (val != null) ? `${val}%` : "—";

        if (waitReductEl) waitReductEl.textContent = formattedVal;
        if (summaryWaitBadge) {
            summaryWaitBadge.textContent = (val != null) ? `${val}% Delay Saved` : "—";
        }
        if (fixedWaitEl) fixedWaitEl.textContent = `${comp.fixed_avg_wait_sec}s`;
        if (adaptiveWaitEl) adaptiveWaitEl.textContent = `${comp.adaptive_avg_wait_sec}s`;
    } else {
        if (waitReductEl) waitReductEl.textContent = "—";
        if (summaryWaitBadge) summaryWaitBadge.textContent = "—";
        if (fixedWaitEl) fixedWaitEl.textContent = "—";
        if (adaptiveWaitEl) adaptiveWaitEl.textContent = "—";
    }
}

/* ==========================================================================
   5. Side-by-Side Original vs Enhanced Toggle Logic
   ========================================================================== */
function toggleVisionView(road) {
    const singleView = document.getElementById(`singleView${capitalize(road)}`);
    const splitView = document.getElementById(`splitView${capitalize(road)}`);
    const toggleText = document.getElementById(`toggleText${capitalize(road)}`);
    const viewStatus = document.getElementById(`viewStatus${capitalize(road)}`);

    if (!singleView || !splitView) return;

    const isSplit = splitView.style.display !== "none";
    if (isSplit) {
        splitView.style.display = "none";
        singleView.style.display = "block";
        if (toggleText) toggleText.textContent = "Compare Original / Enhanced";
        if (viewStatus) viewStatus.textContent = "Annotated Feed";
    } else {
        splitView.style.display = "grid";
        singleView.style.display = "none";
        if (toggleText) toggleText.textContent = "Show Single View";
        if (viewStatus) viewStatus.textContent = "Side-by-Side (Original vs Enhanced)";
    }
}

/* ==========================================================================
   6. API Interactions (Poll, Upload, Simulate, Emergency, Clear, Reset)
   ========================================================================== */
function fetchInitialStatus(isReset = false) {
    fetch("/api/status")
        .then(res => res.json())
        .then(result => {
            if (result.success && result.data) {
                updateDashboardUI(result.data);
                if (isReset) {
                    initSignalCycle(result.data.order, result.data.roads, true);
                } else {
                    // Restore remembered actual counts from localStorage (Item 3)
                    ["north", "south", "east", "west"].forEach(r => {
                        const currentFileName = localStorage.getItem(`traffic_file_${r}`);
                        if (currentFileName) {
                            const remembered = localStorage.getItem(`traffic_actual_${r}_${currentFileName}`);
                            const actualInput = document.getElementById(`actual${capitalize(r)}`);
                            if (actualInput && remembered !== null && actualInput.value === "") {
                                actualInput.value = remembered;
                            }
                        }
                    });
                    logEvent("SYSTEM", "Initialized junction status and lighting detection engine.");
                }
            }
        })
        .catch(err => {
            console.error("Status fetch error:", err);
            logEvent("SYSTEM", "Error fetching junction status from backend.");
        });
}

function startPolling() {
    setInterval(() => {
        if (!isPolling || isSubmitting) return;

        fetch("/api/status")
            .then(res => res.json())
            .then(result => {
                if (result.success && result.data) {
                    if (result.data.timestamp !== currentTrafficState?.timestamp) {
                        updateDashboardUI(result.data);
                    }
                }
            })
            .catch(err => {
                // Silently continue polling on transient network hiccups
            });
    }, 3000);
}

function runSimulation() {
    const btn = document.getElementById("btnSimulate");
    const lightingSelect = document.getElementById("lightingSimSelect");
    const selectedLighting = lightingSelect ? lightingSelect.value : "random";

    setButtonLoading(btn, true, "Simulating...");

    fetch("/api/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lighting: selectedLighting })
    })
    .then(res => res.json())
    .then(result => {
        setButtonLoading(btn, false, '<span class="btn-icon">⚡</span> Run Simulation');
        if (result.success && result.data) {
            updateDashboardUI(result.data);
            const nightNote = result.data.is_night_mode ? " [Night Mode Active]" : "";
            showToast(`Simulation generated for ${selectedLighting.toUpperCase()} lighting${nightNote}!`, "success");
            logEvent("OPTIMIZER", `Simulation updated (${selectedLighting.toUpperCase()}). Wait reduced by ${result.data.comparison.wait_reduction_pct}%.`);
        } else {
            showToast("Simulation error: " + (result.error || "Unknown"), "error");
        }
    })
    .catch(err => {
        setButtonLoading(btn, false, '<span class="btn-icon">⚡</span> Run Simulation');
        showToast("Simulation network error: " + err.message, "error");
    });
}

function uploadTrafficMedia() {
    const btn = document.getElementById("btnAnalyzeTraffic");
    const roads = ["north", "south", "east", "west"];

    // 1. Empty upload check (Requirement 6)
    const hasAnyFile = roads.some(r => {
        const el = document.getElementById(`file${capitalize(r)}`);
        return el && el.files && el.files.length > 0;
    });

    if (!hasAnyFile) {
        showToast("Upload at least one image or video, or use Run Simulation.", "warning");
        logEvent("SYSTEM", "Upload skipped: No files selected. Choose road files or use Run Simulation.");
        return;
    }

    const formData = new FormData();
    const allowedExts = [".jpg", ".jpeg", ".png", ".bmp", ".webp", ".avif", ".heic", ".heif", ".mp4", ".avi", ".mov", ".mkv", ".webm"];
    let attachedCount = 0;

    for (const road of roads) {
        const fileInput = document.getElementById(`file${capitalize(road)}`);
        if (fileInput && fileInput.files && fileInput.files[0]) {
            const file = fileInput.files[0];
            const ext = "." + file.name.split(".").pop().toLowerCase();

            if (!allowedExts.includes(ext)) {
                showToast(`"${file.name}": Unsupported format. Allowed: .jpg, .png, .mp4, .avi, .webm`, "error");
                logEvent("SYSTEM", `Rejected ${file.name} for ${capitalize(road)}: invalid file type`);
                continue;
            }

            if (file.size > 50 * 1024 * 1024) {
                showToast(`"${file.name}": Exceeds 50 MB limit (${(file.size / (1024 * 1024)).toFixed(1)} MB).`, "error");
                logEvent("SYSTEM", `Rejected ${file.name} for ${capitalize(road)}: file exceeds 50 MB`);
                continue;
            }

            formData.append(road, file);
            attachedCount++;
        }
    }

    if (attachedCount === 0) {
        showToast("Upload at least one valid image or video, or use Run Simulation.", "warning");
        return;
    }

    // Attach tuned confidence (Requirement 3)
    const confSlider = document.getElementById("confSlider");
    if (confSlider) {
        formData.append("confidence", confSlider.value);
    }

    // Attach chosen model variant (Requirement 1)
    const modelSelect = document.getElementById("modelSelect");
    if (modelSelect) {
        formData.append("model", modelSelect.value);
    }

    // Attach per-road lighting overrides (Requirement C12)
    ["north", "south", "east", "west"].forEach(road => {
        const ov = document.getElementById(`override${capitalize(road)}`);
        if (ov) {
            formData.append(`lighting_${road}`, ov.value);
        }
    });

    // Attach ground truth actual counts if provided (Requirement 2)
    ["north", "south", "east", "west"].forEach(road => {
        const actualInput = document.getElementById(`actual${capitalize(road)}`);
        if (actualInput && actualInput.value.trim() !== "") {
            formData.append(`actual_${road}`, actualInput.value.trim());
        }
    });

    setButtonLoading(btn, true, "Analyzing Feeds...");
    isSubmitting = true;

    fetch("/api/upload", {
        method: "POST",
        body: formData
    })
    .then(async res => {
        const result = await res.json();
        return { status: res.status, ok: res.ok, result };
    })
    .then(({ status, ok, result }) => {
        setButtonLoading(btn, false, '<span class="btn-icon">🔍</span> Analyze Traffic');
        isSubmitting = false;

        // Show individual per-file error toasts if any bad files occurred
        if (result.errors && Array.isArray(result.errors)) {
            result.errors.forEach(err => showToast(err, "error"));
        }

        if (ok && result.success && result.data) {
            // Remove "Selected, not analyzed" badge for roads analyzed successfully (Item 1)
            roads.forEach(r => {
                const rData = result.data.roads && result.data.roads[r];
                if (rData && !rData.upload_failed) {
                    const fileStatus = document.getElementById(`fileStatus${capitalize(r)}`);
                    if (fileStatus) {
                        fileStatus.style.display = "none";
                        fileStatus.textContent = "";
                    }
                }
            });
            updateDashboardUI(result.data);
            showToast("Traffic feeds processed and signals optimized!", "success");
            logEvent("AI-VISION", `Uploaded media analyzed with YOLOv8. Total vehicles: ${result.data.total_vehicles}. Timings updated.`);
        } else if (!ok) {
            showToast("Upload error: " + (result.error || "Failed to process media"), "error");
            logEvent("SYSTEM", `Upload error: ${result.error}`);
        }
    })
    .catch(err => {
        setButtonLoading(btn, false, '<span class="btn-icon">🔍</span> Analyze Traffic');
        isSubmitting = false;
        showToast("Upload connection error: " + err.message, "error");
    });
}

function loadSampleRoads() {
    const form = document.getElementById("uploadTrafficForm");
    if (form) form.reset();

    const roads = ["north", "south", "east", "west"];
    roads.forEach(r => {
        const textEl = document.getElementById(`fileText${capitalize(r)}`);
        if (textEl) textEl.textContent = "Choose road image/video";

        const statusBadge = document.getElementById(`fileStatus${capitalize(r)}`);
        if (statusBadge) statusBadge.style.display = "none";

        // Reset split views back to single view
        const singleView = document.getElementById(`singleView${capitalize(r)}`);
        const splitView = document.getElementById(`splitView${capitalize(r)}`);
        const toggleText = document.getElementById(`toggleText${capitalize(r)}`);
        const viewStatus = document.getElementById(`viewStatus${capitalize(r)}`);

        if (singleView) singleView.style.display = "block";
        if (splitView) splitView.style.display = "none";
        if (toggleText) toggleText.textContent = "Compare Original / Enhanced";
        if (viewStatus) viewStatus.textContent = "Annotated Feed";
    });

    fetch("/api/samples", { method: "POST" })
        .then(res => res.json())
        .then(resData => {
            if (resData.success && resData.data) {
                updateDashboardUI(resData.data);
                showToast("Loaded sample roads (TEST DATA)", "info");
                logEvent("SYSTEM", "Loaded sample roads under Test tools.");
            }
        })
        .catch(err => {
            showToast("Failed to load samples: " + err.message, "error");
        });
}

function resetDashboard() {
    // Clear form, file inputs, actual count inputs and fileStatus badges
    const form = document.getElementById("uploadTrafficForm");
    if (form) form.reset();
    ["north", "south", "east", "west"].forEach(r => {
        const act = document.getElementById(`actual${capitalize(r)}`);
        if (act) act.value = "";
        const stat = document.getElementById(`fileStatus${capitalize(r)}`);
        if (stat) {
            stat.style.display = "none";
            stat.textContent = "";
        }
        const txt = document.getElementById(`fileText${capitalize(r)}`);
        if (txt) txt.textContent = "Choose road image/video";
        const fn = localStorage.getItem(`traffic_file_${r}`);
        if (fn) {
            localStorage.removeItem(`traffic_actual_${r}_${fn}`);
        }
        localStorage.removeItem(`traffic_file_${r}`);
    });
    // Clean up any lingering traffic_ actual and file keys (Item 3)
    Object.keys(localStorage).forEach(key => {
        if (key.startsWith("traffic_actual_") || key.startsWith("traffic_file_")) {
            localStorage.removeItem(key);
        }
    });

    fetch("/api/reset")
        .then(res => res.json())
        .then(result => {
            clearEventLog();
            showToast("Dashboard reset to initial state", "info");
            fetchInitialStatus(true);
        })
        .catch(err => {
            showToast("Reset failed: " + err.message, "error");
            logEvent("SYSTEM", `Reset error: ${err.message}`);
        });
}

function runEmergencySimulation(road) {
    const lightingSelect = document.getElementById("lightingSimSelect");
    const selectedLighting = lightingSelect ? lightingSelect.value : "random";

    fetch("/api/emergency", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ road: road, lighting: selectedLighting })
    })
    .then(res => res.json())
    .then(result => {
        if (result.success && result.data) {
            updateDashboardUI(result.data);
            const alertMsg = result.data.emergency_message
                || `Emergency vehicle priority granted to [${road.toUpperCase()}] approach.`;
            showToast(`🚨 ${alertMsg}`, "error");
            logEvent("EMERGENCY", `🚨 Emergency priority activated for [${road.toUpperCase()}] corridor without altering vehicle counts.`);
        } else {
            showToast("Emergency simulation error: " + (result.error || "Unknown"), "error");
        }
    })
    .catch(err => {
        showToast("Emergency simulation network error: " + err.message, "error");
    });
}

let isClearingEmergency = false;

function clearEmergencySimulation(silent = false, reason = "manual") {
    if (isClearingEmergency) return;
    if (!currentTrafficState || !currentTrafficState.emergency_road) return;

    isClearingEmergency = true;

    fetch(`/api/emergency/clear?reason=${encodeURIComponent(reason)}`, {
        method: "POST"
    })
    .then(res => res.json())
    .then(result => {
        isClearingEmergency = false;
        if (result.success && result.data) {
            updateDashboardUI(result.data);
            if (!silent) {
                showToast("Emergency override cleared. Normal cycle resumed.", "info");
            }
        }
    })
    .catch(err => {
        isClearingEmergency = false;
        if (!silent) {
            showToast("Clear emergency failed: " + err.message, "error");
        }
    });
}

/* ==========================================================================
   7. Event Listeners & Controls
   ========================================================================== */
function setupEventListeners() {
    // Primary control buttons
    document.getElementById("btnSimulate")?.addEventListener("click", runSimulation);
    document.getElementById("btnAnalyzeTraffic")?.addEventListener("click", uploadTrafficMedia);
    document.getElementById("btnLoadSamples")?.addEventListener("click", loadSampleRoads);
    document.getElementById("btnClearLog")?.addEventListener("click", clearEventLog);
    document.getElementById("btnReset")?.addEventListener("click", resetDashboard);
    document.getElementById("btnClearEmergency")?.addEventListener("click", () => clearEmergencySimulation());
    document.getElementById("btnClearEmergencyBanner")?.addEventListener("click", () => clearEmergencySimulation());
    document.getElementById("btnConfidenceSweep")?.addEventListener("click", runConfidenceSweep);
    document.getElementById("btnClearHistory")?.addEventListener("click", clearRunHistory);

    // Collapsible How It Works toggle
    const btnToggleHIW = document.getElementById("btnToggleHowItWorks");
    const hiwContent = document.getElementById("howItWorksContent");
    const hiwArrow = document.getElementById("hiwToggleArrow");
    btnToggleHIW?.addEventListener("click", () => {
        if (!hiwContent) return;
        const isCollapsed = hiwContent.classList.toggle("collapsed");
        if (hiwArrow) {
            hiwArrow.textContent = isCollapsed ? "▼" : "▲";
        }
        btnToggleHIW.setAttribute("aria-expanded", !isCollapsed);
    });

    // Emergency override buttons
    document.getElementById("btnEmergNorth")?.addEventListener("click", () => runEmergencySimulation("north"));
    document.getElementById("btnEmergSouth")?.addEventListener("click", () => runEmergencySimulation("south"));
    document.getElementById("btnEmergEast")?.addEventListener("click", () => runEmergencySimulation("east"));
    document.getElementById("btnEmergWest")?.addEventListener("click", () => runEmergencySimulation("west"));

    // File Input Name Listeners
    const roads = ["north", "south", "east", "west"];
    roads.forEach(r => {
        const fileInput = document.getElementById(`file${capitalize(r)}`);
        const labelText = document.getElementById(`fileText${capitalize(r)}`);

        fileInput?.addEventListener("change", (e) => {
            if (e.target.files && e.target.files[0]) {
                const file = e.target.files[0];
                if (labelText) {
                    labelText.textContent = file.name;
                    labelText.title = file.name;
                }
                const fileStatus = document.getElementById(`fileStatus${capitalize(r)}`);
                if (fileStatus) {
                    fileStatus.textContent = "Selected, not analyzed";
                    fileStatus.style.display = "inline-block";
                }

                // If image, preview in card immediately
                if (file.type.startsWith("image/")) {
                    const reader = new FileReader();
                    reader.onload = (re) => {
                        const img = document.getElementById(`img${capitalize(r)}`);
                        if (img) img.src = re.target.result;
                    };
                    reader.readAsDataURL(file);
                }

                // Requirement 3: Remember each road's Actual count in localStorage keyed by road and file name
                const prevFile = localStorage.getItem(`traffic_file_${r}`);
                if (prevFile && prevFile !== file.name) {
                    // Different file chosen for that road -> clear old file's remembered actual count
                    localStorage.removeItem(`traffic_actual_${r}_${prevFile}`);
                }
                localStorage.setItem(`traffic_file_${r}`, file.name);

                const actInput = document.getElementById(`actual${capitalize(r)}`);
                if (actInput) {
                    const remembered = localStorage.getItem(`traffic_actual_${r}_${file.name}`);
                    actInput.value = (remembered !== null) ? remembered : "";
                }

                logEvent("SYSTEM", `File selected for ${capitalize(r)} Approach: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`);
            }
        });

        // Actual count input listener (Requirement 3: save to localStorage keyed by road and file name)
        const actInput = document.getElementById(`actual${capitalize(r)}`);
        actInput?.addEventListener("input", (e) => {
            const fi = document.getElementById(`file${capitalize(r)}`);
            const currentFileName = fi?.files?.[0]?.name || localStorage.getItem(`traffic_file_${r}`);
            if (currentFileName) {
                if (e.target.value.trim() !== "") {
                    localStorage.setItem(`traffic_actual_${r}_${currentFileName}`, e.target.value.trim());
                } else {
                    localStorage.removeItem(`traffic_actual_${r}_${currentFileName}`);
                }
            }
        });
    });

    // Close modal on escape
    window.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            closeImageModal();
        }
    });

    // Detection Settings: Confidence slider listener
    const confSlider = document.getElementById("confSlider");
    const confValBadge = document.getElementById("confSliderVal");
    confSlider?.addEventListener("input", (e) => {
        if (confValBadge) {
            confValBadge.textContent = Number(e.target.value).toFixed(2);
        }
    });

    // History filter: Show test runs checkbox (Item 4)
    document.getElementById("chkShowTestRuns")?.addEventListener("change", () => {
        if (cachedRunHistory) {
            renderRunHistory(cachedRunHistory);
        }
    });
}

/* ==========================================================================
   8. Helper Functions & Modals
   ========================================================================== */
function capitalize(str) {
    if (!str) return "";
    return str.charAt(0).toUpperCase() + str.slice(1);
}

/**
 * setButtonLoading - Toggle a button's loading state, preserving its original HTML.
 */
function setButtonLoading(btn, isLoading, text) {
    if (!btn) return;
    btn.disabled = isLoading;
    if (isLoading) {
        if (!btn.dataset.originalHtml) {
            btn.dataset.originalHtml = btn.innerHTML;
        }
        btn.innerHTML = `<span class="btn-spinner"></span> ${text}`;
    } else {
        btn.innerHTML = btn.dataset.originalHtml || text;
        btn.dataset.originalHtml = "";
    }
}

function logEvent(badgeType, message) {
    const terminal = document.getElementById("logTerminal");
    if (!terminal) return;

    const timeStr = new Date().toTimeString().split(" ")[0];
    const entry = document.createElement("div");
    entry.className = "log-entry";

    let badgeClass = "badge-system";
    if (badgeType === "SIGNAL")          badgeClass = "badge-signal";
    else if (badgeType === "AI-VISION")  badgeClass = "badge-vision";
    else if (badgeType === "OPTIMIZER")  badgeClass = "badge-optimizer";
    else if (badgeType === "LOW-LIGHT")  badgeClass = "badge-lowlight";
    else if (badgeType === "NIGHT-CV")   badgeClass = "badge-night";
    else if (badgeType === "EMERGENCY")  badgeClass = "badge-emergency";

    entry.innerHTML = `
        <span class="log-time">[${timeStr}]</span>
        <span class="log-badge ${badgeClass}">${badgeType}</span>
        <span class="log-msg">${escapeHtml(message)}</span>
    `;

    terminal.appendChild(entry);
    terminal.scrollTop = terminal.scrollHeight;
}

function clearEventLog() {
    const terminal = document.getElementById("logTerminal");
    if (terminal) {
        terminal.innerHTML = "";
        loggedMessageSet.clear();
        logEvent("SYSTEM", "Event log cleared.");
    }
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function showToast(message, type = "info") {
    const container = document.getElementById("toastContainer");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    const icon = type === "success" ? "✅" : (type === "error" ? "❌" : "ℹ️");
    toast.innerHTML = `<span>${icon}</span> <span>${escapeHtml(message)}</span>`;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateX(50px)";
        setTimeout(() => toast.remove(), 300);
    }, 3800);
}

/* Modal Functions */
function openImageModal(imgId) {
    const img = document.getElementById(imgId);
    const modal = document.getElementById("imageModal");
    const modalImg = document.getElementById("modalImage");
    const modalTitle = document.getElementById("modalTitle");

    if (img && modal && modalImg) {
        modalImg.src = img.src;
        if (modalTitle) modalTitle.textContent = `${img.alt || "Detection Inspection"} (Full Resolution)`;
        modal.classList.add("open");
    }
}

function openCustomImageModal(imgId, title) {
    const img = document.getElementById(imgId);
    const modal = document.getElementById("imageModal");
    const modalImg = document.getElementById("modalImage");
    const modalTitle = document.getElementById("modalTitle");

    if (img && modal && modalImg) {
        modalImg.src = img.src;
        if (modalTitle) modalTitle.textContent = title;
        modal.classList.add("open");
    }
}

function closeImageModal() {
    const modal = document.getElementById("imageModal");
    if (modal) modal.classList.remove("open");
}

/* ==========================================================================
   9. Confidence Sweep Analysis (Requirement C14)
   ========================================================================== */
function runConfidenceSweep() {
    const btn = document.getElementById("btnConfidenceSweep");
    setButtonLoading(btn, true, "Running sweep...");
    showToast("🔍 Running confidence sweep across 0.20, 0.30, 0.40, 0.50...", "info");

    const formData = new FormData(document.getElementById("uploadTrafficForm"));
    const modelSelect = document.getElementById("modelSelect");
    if (modelSelect) formData.append("model", modelSelect.value);

    fetch("/api/confidence_sweep", {
        method: "POST",
        body: formData
    })
    .then(res => res.json())
    .then(result => {
        setButtonLoading(btn, false, '<span>🔍</span> Run confidence sweep');
        if (result.success && result.results) {
            renderConfidenceSweepTable(result.results, result.model);
            showToast("Confidence sweep completed!", "success");
            logEvent("AI-VISION", `Confidence sweep executed across 0.20-0.50 using ${result.model}.`);
        } else {
            showToast(result.error || "Sweep failed. Choose road files or analyze traffic first.", "error");
        }
    })
    .catch(err => {
        setButtonLoading(btn, false, '<span>🔍</span> Run confidence sweep');
        showToast("Sweep error: " + err.message, "error");
    });
}

function renderConfidenceSweepTable(results, model) {
    const container = document.getElementById("confidenceSweepResults");
    const tbody = document.getElementById("sweepTableBody");
    const modelTag = document.getElementById("sweepModelTag");
    if (!container || !tbody) return;

    if (modelTag) modelTag.textContent = model ? model.toUpperCase() : "YOLOv8s";
    tbody.innerHTML = results.map(row => {
        const fmtRoad = (r) => {
            const rd = row.roads[r];
            if (!rd) return "—";
            const errStr = rd.error_pct != null ? ` <span class="sweep-err">(${rd.error_pct}%)</span>` : "";
            return `${rd.detected} veh${errStr}`;
        };
        const maeStr = row.mae != null ? `${row.mae} veh` : "—";
        return `
            <tr>
                <td class="font-mono font-bold">conf ${row.confidence.toFixed(2)}</td>
                <td class="font-mono font-bold">${row.total_vehicles}</td>
                <td class="font-mono">${fmtRoad("north")}</td>
                <td class="font-mono">${fmtRoad("south")}</td>
                <td class="font-mono">${fmtRoad("east")}</td>
                <td class="font-mono">${fmtRoad("west")}</td>
                <td class="font-mono text-cyan font-bold">${maeStr}</td>
            </tr>
        `;
    }).join("");
    container.style.display = "block";
}

/* ==========================================================================
   10. Run History Visualizations & API Interactions
   ========================================================================== */
function initHistoryCharts() {
    const ctxRed = document.getElementById("historyReductionChart");
    const ctxCounts = document.getElementById("historyCountsChart");

    if (ctxRed) {
        historyReductionChart = new Chart(ctxRed, {
            type: "line",
            data: {
                labels: [],
                datasets: [{
                    label: "Delay Reduction (%)",
                    data: [],
                    borderColor: "#00f298",
                    backgroundColor: "rgba(0, 242, 152, 0.15)",
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3,
                    pointBackgroundColor: "#00f298",
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    spanGaps: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: "#121826",
                        titleColor: "#f0f4fc",
                        bodyColor: "#94a3b8",
                        borderColor: "rgba(255,255,255,0.1)",
                        borderWidth: 1,
                        callbacks: {
                            title: (items) => {
                                // Show full timestamp in tooltip title
                                const idx = items[0]?.dataIndex;
                                return historyReductionChart._runTimestamps?.[idx] || items[0]?.label || "";
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 60,
                        grid: { color: "rgba(255, 255, 255, 0.05)" },
                        ticks: {
                            color: "#64748b",
                            font: { family: "JetBrains Mono" },
                            callback: val => `${val}%`
                        }
                    },
                    x: {
                        grid: { display: false },
                        ticks: {
                            color: "#94a3b8",
                            font: { family: "JetBrains Mono", size: 10 },
                            maxRotation: 0,
                            minRotation: 0,
                            autoSkip: true
                        }
                    }
                }
            }
        });
    }

    if (ctxCounts) {
        historyCountsChart = new Chart(ctxCounts, {
            type: "bar",
            data: {
                labels: [],
                datasets: [
                    { label: "North", data: [], backgroundColor: "rgba(0, 229, 255, 0.75)", borderRadius: 4 },
                    { label: "South", data: [], backgroundColor: "rgba(59, 130, 246, 0.75)", borderRadius: 4 },
                    { label: "East", data: [], backgroundColor: "rgba(255, 51, 102, 0.75)", borderRadius: 4 },
                    { label: "West", data: [], backgroundColor: "rgba(255, 184, 0, 0.75)", borderRadius: 4 }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "top",
                        labels: { color: "#94a3b8", font: { size: 10, family: "Inter" }, boxWidth: 10 }
                    },
                    tooltip: {
                        backgroundColor: "#121826",
                        titleColor: "#f0f4fc",
                        bodyColor: "#94a3b8",
                        borderColor: "rgba(255,255,255,0.1)",
                        borderWidth: 1,
                        callbacks: {
                            title: (items) => {
                                const idx = items[0]?.dataIndex;
                                const ts = historyCountsChart._runTimestamps?.[idx] || items[0]?.label || "";
                                const isEmerg = historyCountsChart._isEmergency?.[idx];
                                const emRoad = historyCountsChart._emergRoad?.[idx];
                                return isEmerg ? `${ts} 🚨 [EMERGENCY PRIORITY: ${emRoad.toUpperCase()}]` : ts;
                            },
                            afterTitle: (items) => {
                                const idx = items[0]?.dataIndex;
                                if (historyCountsChart._isEmergency?.[idx]) {
                                    return ["🚨 Emergency Override Active (Max Green: 60s)"];
                                }
                                return [];
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: "rgba(255, 255, 255, 0.05)" },
                        ticks: { color: "#64748b", font: { family: "JetBrains Mono" } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: {
                            color: "#94a3b8",
                            font: { family: "JetBrains Mono", size: 10 },
                            maxRotation: 0,
                            minRotation: 0,
                            autoSkip: true
                        }
                    }
                }
            }
        });
    }
}

let cachedRunHistory = [];

function fetchRunHistory() {
    fetch("/api/history")
        .then(res => res.json())
        .then(res => {
            if (res.success && Array.isArray(res.history)) {
                cachedRunHistory = res.history;
                renderRunHistory(res.history);
            }
        })
        .catch(err => {
            console.error("Run history fetch failed:", err);
        });
}

function renderRunHistory(history) {
    if (Array.isArray(history)) {
        cachedRunHistory = history;
    }
    const tbody = document.getElementById("historyTableBody");
    if (!tbody) return;

    if (!history || history.length === 0) {
        tbody.innerHTML = '<tr><td colspan="11" class="history-empty-cell">No runs recorded yet. Click Run Simulation or Analyze Traffic to generate optimization records.</td></tr>';
        if (historyReductionChart) {
            historyReductionChart.data.labels = [];
            historyReductionChart.data.datasets[0].data = [];
            historyReductionChart.update();
        }
        if (historyCountsChart) {
            historyCountsChart.data.labels = [];
            historyCountsChart.data.datasets.forEach(ds => ds.data = []);
            historyCountsChart.update();
        }
        return;
    }

    // Populate Table (Most recent run first)
    const reversedHistory = [...history].reverse();
    tbody.innerHTML = reversedHistory.map(item => {
        const timePart = item.timestamp ? item.timestamp.split(" ")[1] || item.timestamp : "--";
        const counts = item.counts || {};
        const greens = item.green_times || {};
        const isEmerg = !!item.emergency_road;
        const statusBadge = isEmerg 
            ? `<span class="badge-hist-emerg">🚨 ${item.emergency_road.toUpperCase()}</span>` 
            : `<span class="badge-hist-norm">NORMAL</span>`;

        const greenStr = `${greens.north || 0}s / ${greens.south || 0}s / ${greens.east || 0}s / ${greens.west || 0}s`;
        const waitReductionDisplay = isEmerg 
            ? `<span class="text-muted" style="font-style: italic;">n/a (priority)</span>` 
            : `<span class="text-green font-bold">${item.wait_reduction_pct != null ? item.wait_reduction_pct + "%" : "0%"}</span>`;

        // Upload History Rows: label rows as "Upload (N, E)" with file names in tooltip
        let modeDisplay = escapeHtml(item.mode || "Unknown");
        if (item.uploaded_files && Object.keys(item.uploaded_files).length > 0) {
            const fileList = Object.entries(item.uploaded_files)
                .map(([r, fn]) => `${capitalize(r)}: ${fn}`)
                .join(" | ");
            modeDisplay = `<span title="${escapeHtml(fileList)}" style="cursor: help; text-decoration: underline dotted; color: #a5b4fc;">${modeDisplay}</span>`;
        }

        return `
            <tr>
                <td>${escapeHtml(timePart)}</td>
                <td>${modeDisplay}</td>
                <td>${escapeHtml(item.lighting || "day")}</td>
                <td>${counts.north ?? 0}</td>
                <td>${counts.south ?? 0}</td>
                <td>${counts.east ?? 0}</td>
                <td>${counts.west ?? 0}</td>
                <td><strong>${item.total_vehicles ?? 0}</strong></td>
                <td>${greenStr}</td>
                <td>${waitReductionDisplay}</td>
                <td>${statusBadge}</td>
            </tr>
        `;
    }).join("");

    // Requirement 4: Hide Test rows from both history charts by default, with a "Show test runs" checkbox
    const chkShowTestRuns = document.getElementById("chkShowTestRuns");
    const showTestRuns = chkShowTestRuns ? chkShowTestRuns.checked : false;
    const chartHistory = showTestRuns 
        ? history 
        : history.filter(h => !(h.mode && (h.mode.includes("Test") || h.mode.includes("Simulation"))));

    // Update Line Chart (Reduction % across runs)
    if (historyReductionChart) {
        const labels = chartHistory.map((_, i) => `#${i + 1}`);
        const timestamps = chartHistory.map(h => h.timestamp || "");
        historyReductionChart.data.labels = labels;
        historyReductionChart.data.datasets[0].data = chartHistory.map(h => h.emergency_road ? null : (h.wait_reduction_pct || 0));
        historyReductionChart.data.datasets[0].pointStyle = chartHistory.map(h => h.emergency_road ? "triangle" : "circle");
        historyReductionChart._runTimestamps = timestamps;
        historyReductionChart.update();
    }

    // Update Grouped Bar Chart (Counts per road across runs)
    if (historyCountsChart) {
        const labels = chartHistory.map((_, i) => `#${i + 1}`);
        const timestamps = chartHistory.map(h => h.timestamp || "");
        historyCountsChart.data.labels = labels;
        historyCountsChart.data.datasets[0].data = chartHistory.map(h => h.counts?.north || 0);
        historyCountsChart.data.datasets[1].data = chartHistory.map(h => h.counts?.south || 0);
        historyCountsChart.data.datasets[2].data = chartHistory.map(h => h.counts?.east || 0);
        historyCountsChart.data.datasets[3].data = chartHistory.map(h => h.counts?.west || 0);
        historyCountsChart._runTimestamps = timestamps;
        historyCountsChart._isEmergency = chartHistory.map(h => !!h.emergency_road);
        historyCountsChart._emergRoad = chartHistory.map(h => h.emergency_road || "");
        historyCountsChart.update();
    }
}

function clearRunHistory() {
    if (!confirm("Are you sure you want to clear all stored optimization history?")) return;

    fetch("/api/history/clear", { method: "POST" })
        .then(res => res.json())
        .then(res => {
            if (res.success) {
                renderRunHistory([]);
                showToast("Run history cleared.", "info");
                logEvent("SYSTEM", "Optimization run history cleared by user.");
            }
        })
        .catch(err => {
            showToast("Failed to clear history: " + err.message, "error");
        });
}
