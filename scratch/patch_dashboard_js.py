import re

with open("static/js/dashboard.js", "r", encoding="utf-8") as f:
    content = f.read()

start_marker = "/* ==========================================================================\n   4. UI Updating & Rendering (Night Mode, Emergency, Badges, Telemetry)\n   ========================================================================== */"
end_marker = "/* ==========================================================================\n   4a. Performance Summary Panel\n   ========================================================================== */"

if start_marker not in content:
    raise ValueError("start_marker not found")
if end_marker not in content:
    raise ValueError("end_marker not found")

idx1 = content.index(start_marker)
idx2 = content.index(end_marker)

replacement = start_marker + """
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

    if (headerCycle) headerCycle.textContent = `${data.cycle_time || 120}s`;
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
            accSummaryText.textContent = `Night Vision Active (${nightCorridorCount} Corridors)`;
        } else if (duskCorridorCount > 0) {
            accSummaryText.textContent = `Low-Light Boost Active (${duskCorridorCount} Corridors)`;
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
\n"""

new_content = content[:idx1] + replacement + content[idx2:]

# Now let's update updateSummaryPanel
summary_start = "function updateSummaryPanel(data) {"
summary_end = "/* ==========================================================================\n   5. Side-by-Side Original vs Enhanced Toggle Logic"

if summary_start in new_content:
    s_idx1 = new_content.index(summary_start)
    s_idx2 = new_content.index(summary_end)
    summary_replacement = """function updateSummaryPanel(data) {
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
\n"""
    new_content = new_content[:s_idx1] + summary_replacement + new_content[s_idx2:]

with open("static/js/dashboard.js", "w", encoding="utf-8") as f:
    f.write(new_content)

print("dashboard.js updated successfully.")
