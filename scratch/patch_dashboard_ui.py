with open("static/js/dashboard.js", "r", encoding="utf-8") as f:
    js = f.read()

start_marker = "/* ==========================================================================\n   4. UI Updating & Rendering"
end_marker = "/* ==========================================================================\n   5. Real-Time 4-Way Traffic Signal State Machine"

idx1 = js.find(start_marker)
idx2 = js.find(end_marker)

if idx1 == -1 or idx2 == -1:
    raise ValueError(f"Could not find updateDashboardUI section markers: {idx1}, {idx2}")

new_ui_section = '''/* ==========================================================================
   4. UI Updating & Rendering (Night Mode, Emergency, Badges, Telemetry)
   ========================================================================== */
function updateDashboardUI(data) {
    if (!data || !data.roads) return;

    currentTrafficState = data;

    // 0. Waiting For Photos Notice & Emergency Buttons Enabled State (Requirement A2 & A5)
    const waitingNotice = document.getElementById("waitingNotice");
    const hasAnalyzed = data.has_analyzed_data === true;

    if (waitingNotice) {
        waitingNotice.style.display = hasAnalyzed ? "none" : "block";
    }

    ["North", "South", "East", "West"].forEach(r => {
        const btnEmerg = document.getElementById(`btnEmerg${r}`);
        if (btnEmerg) {
            btnEmerg.disabled = !hasAnalyzed;
            if (!hasAnalyzed) {
                btnEmerg.title = "Analyze traffic first";
                btnEmerg.classList.add("btn-disabled");
            } else {
                btnEmerg.title = `Trigger emergency override for ${r} approach`;
                btnEmerg.classList.remove("btn-disabled");
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
        let m = "Default fixed timer (no data yet)";
        if (data.emergency_road) {
            m = "Emergency";
        } else if (data.is_test_data || (data.mode && data.mode.toLowerCase().includes("test"))) {
            m = "Test (random data)";
        } else if (hasAnalyzed || (data.mode && data.mode.toLowerCase().includes("upload"))) {
            m = data.mode || "Upload";
        } else {
            m = "Default fixed timer (no data yet)";
        }
        modeIndicator.textContent = m;

        if (modeExplainer) {
            if (m === "Emergency") {
                modeExplainer.textContent = "(Priority override active on emergency corridor)";
            } else if (m === "Test (random data)") {
                modeExplainer.textContent = "(Simulated test data generated for testing only)";
            } else if (m.startsWith("Upload")) {
                modeExplainer.textContent = "(Real camera feeds processed with YOLOv8)";
            } else {
                modeExplainer.textContent = "(Signals on equal 30s timers awaiting uploads)";
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

        const countEl = document.getElementById(`countVal${capitalize(road)}`);
        const greenEl = document.getElementById(`greenVal${capitalize(road)}`);
        const shareEl = document.getElementById(`shareVal${capitalize(road)}`);
        const badgeEl = document.getElementById(`densityBadge${capitalize(road)}`);
        const lightBadge = document.getElementById(`lightingBadge${capitalize(road)}`);
        const lightText = document.getElementById(`lightingText${capitalize(road)}`);
        const emergBadge = document.getElementById(`emergBadge${capitalize(road)}`);
        const sampleBadge = document.getElementById(`sampleBadge${capitalize(road)}`);
        const testBadge = document.getElementById(`testDataBadge${capitalize(road)}`);
        const prevBadge = document.getElementById(`previousBadge${capitalize(road)}`);
        const noDataBadge = document.getElementById(`noDataBadge${capitalize(road)}`);
        const failedBanner = document.getElementById(`uploadFailed${capitalize(road)}`);
        const dupNote = document.getElementById(`duplicateNote${capitalize(road)}`);
        const fileStatus = document.getElementById(`fileStatus${capitalize(road)}`);
        const engineBadge = document.getElementById(`engineBadge${capitalize(road)}`);
        const videoStats = document.getElementById(`videoStats${capitalize(road)}`);
        const videoAvg = document.getElementById(`videoAvg${capitalize(road)}`);
        const videoMax = document.getElementById(`videoMax${capitalize(road)}`);
        const roadCard = document.getElementById(`card${capitalize(road)}`);

        // Counts display: show "—" when count is null (Requirement A2)
        if (countEl) countEl.textContent = (rData.count != null) ? rData.count : "—";
        if (greenEl) greenEl.textContent = `${rData.green_time}s`;
        if (shareEl) shareEl.textContent = (rData.count != null) ? `${rData.share_pct || 0}%` : "—";

        if (badgeEl) {
            if (rData.no_data || rData.density === "—") {
                badgeEl.textContent = "—";
                badgeEl.className = "density-badge badge-nodata";
            } else {
                badgeEl.textContent = rData.density;
                badgeEl.className = `density-badge badge-${rData.density.toLowerCase()}`;
            }
        }

        // Engine badge on road card — derived strictly from state
        if (engineBadge) {
            if (rData.upload_failed) {
                engineBadge.textContent = "Engine: Upload failed";
            } else if (rData.is_test_data || data.is_test_data || (data.data_source === "simulation")) {
                engineBadge.textContent = "Engine: Simulated";
            } else if (rData.is_previous) {
                engineBadge.textContent = "Engine: Previous";
            } else if (rData.no_data) {
                engineBadge.textContent = "Engine: No data";
            } else if (rData.is_sample) {
                engineBadge.textContent = "Engine: Sample images";
            } else {
                let eng = rData.engine || "YOLOv8s";
                if (eng.toLowerCase().includes("opencv")) {
                    eng = "OpenCV fallback";
                }
                const confStr = rData.conf_threshold != null ? Number(rData.conf_threshold).toFixed(2) : confVal;
                engineBadge.textContent = `Engine: ${eng} (conf ${confStr})`;
            }
        }

        // Status tags on road card
        if (testBadge) testBadge.style.display = (rData.is_test_data || data.is_test_data) ? "inline-block" : "none";
        if (prevBadge) prevBadge.style.display = rData.is_previous ? "inline-block" : "none";
        if (noDataBadge) noDataBadge.style.display = (rData.no_data && !rData.upload_failed) ? "inline-block" : "none";
        if (sampleBadge) sampleBadge.style.display = (rData.is_sample && !rData.is_test_data && !data.is_test_data) ? "inline-block" : "none";

        // Upload failed banner
        if (failedBanner) {
            if (rData.upload_failed) {
                failedBanner.textContent = `❌ Upload failed: ${rData.error_reason || "Corrupted media"}`;
                failedBanner.style.display = "block";
            } else {
                failedBanner.style.display = "none";
            }
        }

        // Duplicate file note banner
        if (dupNote) {
            if (rData.is_duplicate) {
                dupNote.textContent = `ℹ️ ${rData.duplicate_file_note || "Identical media uploaded"}`;
                dupNote.style.display = "block";
            } else {
                dupNote.style.display = "none";
            }
        }

        // If road has been analyzed, hide file selection status badge
        if (hasAnalyzed && !rData.is_previous && !rData.no_data && fileStatus) {
            fileStatus.style.display = "none";
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
            lightBadge.innerHTML = `<span class="badge-icon">${icon}</span> <span class="badge-text" id="lightingText${capitalize(road)}">${label} (${brightness})</span>`;
        }

        // Feed Images
        const ts = Date.now();
        const mainUrl = rData.image_url ? `${rData.image_url.split("?")[0]}?t=${ts}` : "";
        const origUrl = rData.original_image_url ? `${rData.original_image_url.split("?")[0]}?t=${ts}` : mainUrl;
        const enhUrl = rData.enhanced_image_url ? `${rData.enhanced_image_url.split("?")[0]}?t=${ts}` : mainUrl;

        const imgSingle = document.getElementById(`img${capitalize(road)}`);
        const imgOrig = document.getElementById(`img${capitalize(road)}Orig`);
        const imgEnh = document.getElementById(`img${capitalize(road)}Enh`);
        const btnToggle = document.getElementById(`btnToggle${capitalize(road)}`);

        if (imgSingle) imgSingle.src = mainUrl;
        if (imgOrig) imgOrig.src = origUrl;
        if (imgEnh) imgEnh.src = enhUrl;

        if (btnToggle) {
            if (lMode === "night") {
                btnToggle.classList.add("highlight-night");
            } else {
                btnToggle.classList.remove("highlight-night");
            }
        }

        // Accuracy Telemetry
        const accLight = document.getElementById(`accLighting${capitalize(road)}`);
        const accPipe = document.getElementById(`accPipeline${capitalize(road)}`);
        const accBrightVal = document.getElementById(`accBrightVal${capitalize(road)}`);
        const accMeter = document.getElementById(`accMeter${capitalize(road)}`);
        const accDesc = document.getElementById(`accDesc${capitalize(road)}`);

        if (accLight) {
            let tagText = "☀️ DAY";
            if (lMode === "dusk") tagText = "🌆 DUSK";
            else if (lMode === "night") tagText = "🌙 NIGHT";
            accLight.textContent = tagText;
            accLight.className = `acc-lighting-tag tag-${lMode}`;
        }

        const ds = rData.data_source || data.data_source || "sample";
        if (accPipe) {
            if (rData.upload_failed) {
                accPipe.textContent = "Upload failed (undecodable media)";
            } else if (rData.no_data) {
                accPipe.textContent = "No data yet (waiting for uploads)";
            } else if (rData.is_previous) {
                accPipe.textContent = "Previous analyzed feed";
            } else if (ds === "simulation" || rData.is_test_data || data.is_test_data) {
                accPipe.textContent = "Simulated counts (no detection run)";
            } else if (ds === "sample" || rData.is_sample) {
                accPipe.textContent = "Sample Benchmark Feed (no live detection)";
            } else {
                let eng = rData.engine || "YOLOv8s";
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
            if (rData.upload_failed) {
                accDesc.textContent = `Upload failed: ${rData.error_reason || "Corrupted media"}.`;
            } else if (rData.no_data) {
                accDesc.textContent = "Approach has not been uploaded yet. Standard safety minimum allocated.";
            } else if (rData.is_previous) {
                accDesc.textContent = "Retained vehicle density from previous analysis cycle.";
            } else if (ds === "simulation" || rData.is_test_data || data.is_test_data) {
                accDesc.textContent = "Simulated counts (no detection run)";
            } else if (ds === "sample" || rData.is_sample) {
                accDesc.textContent = "Pre-computed baseline benchmark image — camera feeds not currently uploaded.";
            } else {
                let eng = rData.engine || "YOLOv8s";
                if (eng.toLowerCase().includes("opencv")) eng = "OpenCV fallback";
                const confStr = rData.conf_threshold != null ? Number(rData.conf_threshold).toFixed(2) : confVal;
                if (lMode === "night") {
                    accDesc.textContent = `Night scene: LAB CLAHE & adaptive gamma boost shadow details + dual-headlight pairing. Engine: ${eng} (conf ${confStr}).`;
                } else if (lMode === "dusk") {
                    accDesc.textContent = `Dusk low-light: Adaptive gamma & CLAHE applied to amplify vehicle contrast. Engine: ${eng} (conf ${confStr}).`;
                } else {
                    accDesc.textContent = `Daylight scene: ${eng} detection, conf=${confStr}, COCO vehicle classes (car, motorcycle, bus, truck).`;
                }
            }
        }
    });

    // 3b. Upload warning banners (0 or 1 vehicles detected on uploaded images)
    const isUploadMode = (data.mode || "").toLowerCase().includes("upload");
    ["north", "south", "east", "west"].forEach(road => {
        const warnEl = document.getElementById(`uploadWarning${capitalize(road)}`);
        if (!warnEl) return;
        const rData = data.roads[road];
        if (!rData) { warnEl.style.display = "none"; return; }
        // Show warning only for upload mode roads that are NOT samples and have <=1 count and did not fail
        if (isUploadMode && !rData.is_sample && !rData.no_data && !rData.upload_failed && rData.count != null && rData.count <= 1) {
            warnEl.style.display = "block";
        } else {
            warnEl.style.display = "none";
        }
    });

    // 3c. Ground truth actual count feedback on card & Accuracy Report panel
    ["north", "south", "east", "west"].forEach(road => {
        const feedbackEl = document.getElementById(`accuracyFeedback${capitalize(road)}`);
        const rData = data.roads[road];
        if (!feedbackEl || !rData) return;

        if (rData.accuracy_feedback) {
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
        maeValEl.textContent = hasReport ? `${accReport.mae} veh` : "--";
    }

    if (hasReport && reportWrapper && reportTbody) {
        if (reportPlaceholder) reportPlaceholder.style.display = "none";
        reportWrapper.style.display = "block";
        reportTbody.innerHTML = ["north", "south", "east", "west"].map(road => {
            const item = accReport.per_road?.[road];
            if (!item) return "";
            if (!item.analyzed) {
                return `
                    <tr>
                        <td><strong>${capitalize(road)} Approach</strong></td>
                        <td class="font-mono">${item.detected != null ? item.detected + " veh" : "—"}</td>
                        <td class="font-mono text-blue font-bold">${item.actual != null ? item.actual + " veh" : "—"}</td>
                        <td class="font-mono">—</td>
                        <td class="font-mono text-muted">n/a (not analyzed)</td>
                        <td><span class="badge-acc-dev">Not Analyzed</span></td>
                    </tr>
                `;
            }
            if (item.actual === null) {
                return `
                    <tr>
                        <td><strong>${capitalize(road)} Approach</strong></td>
                        <td class="font-mono">${item.detected} veh</td>
                        <td class="font-mono text-muted">—</td>
                        <td class="font-mono">—</td>
                        <td class="font-mono text-muted">—</td>
                        <td><span class="badge-acc-med">No ground truth</span></td>
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
        }).join("");
    } else {
        if (reportPlaceholder) reportPlaceholder.style.display = "block";
        if (reportWrapper) reportWrapper.style.display = "none";
    }

    // Accuracy Summary Pill (Requirement 6: Simulation mode shows "Simulation Mode - no detection run")
    const isSimMode = data.data_source === "simulation" || (data.mode || "").toLowerCase().includes("simulation") || data.is_test_data;
    const accSummaryText = document.getElementById("accuracySummaryText");
    if (accSummaryText) {
        if (isSimMode) {
            accSummaryText.textContent = "Simulation Mode - no detection run";
        } else if (!hasAnalyzed) {
            accSummaryText.textContent = "Waiting for uploads";
        } else if (nightCorridorCount > 0) {
            accSummaryText.textContent = `Night-Mode CV Active (${nightCorridorCount} dark corridor${nightCorridorCount > 1 ? "s" : ""})`;
        } else if (duskCorridorCount > 0) {
            accSummaryText.textContent = `Dusk CLAHE Active (${duskCorridorCount} dim corridor${duskCorridorCount > 1 ? "s" : ""})`;
        } else {
            accSummaryText.textContent = "Daylight Silhouette Sensors Active";
        }
    }

    // 4. Comparison Cards (Fixed vs Adaptive)
    const comp = data.comparison || {};
    const valFixed = document.getElementById("valFixedWait");
    const valAdapt = document.getElementById("valAdaptiveWait");
    const badgeSavings = document.getElementById("savingsBadge");
    const kpiRed = document.getElementById("kpiReductionPct");
    const kpiCongFixed = document.getElementById("kpiCongestionFixed");
    const kpiCongAdapt = document.getElementById("kpiCongestionAdaptive");
    const adaptNote = document.getElementById("adaptiveEfficiencyNote");
    const effBar = document.getElementById("efficiencyProgressBar");
    const effLabel = document.getElementById("efficiencyPctLabel");

    if (valFixed) valFixed.textContent = comp.fixed_avg_wait_sec != null ? `${comp.fixed_avg_wait_sec.toFixed(1)}s` : "--s";
    if (valAdapt) valAdapt.textContent = comp.adaptive_avg_wait_sec != null ? `${comp.adaptive_avg_wait_sec.toFixed(1)}s` : "--s";

    const waitRedPct = comp.wait_reduction_pct != null ? comp.wait_reduction_pct.toFixed(1) : "0.0";
    if (badgeSavings) {
        badgeSavings.textContent = `${waitRedPct}% Less Delay`;
    }
    if (kpiRed) kpiRed.textContent = `${waitRedPct}%`;

    if (kpiCongFixed) kpiCongFixed.textContent = comp.congestion_index_fixed ? `${comp.congestion_index_fixed.toFixed(2)}x` : "1.00x";
    if (kpiCongAdapt) kpiCongAdapt.textContent = comp.congestion_index_adaptive ? `${comp.congestion_index_adaptive.toFixed(2)}x` : "1.00x";

    if (adaptNote && comp.fixed_avg_wait_sec != null && comp.adaptive_avg_wait_sec != null) {
        const saved = (comp.fixed_avg_wait_sec - comp.adaptive_avg_wait_sec).toFixed(1);
        adaptNote.textContent = `${saved}s Saved per Vehicle`;
    }

    const effPct = comp.clearance_efficiency_pct != null ? Math.round(comp.clearance_efficiency_pct) : 80;
    if (effBar) effBar.style.width = `${effPct}%`;
    if (effLabel) effLabel.textContent = `${effPct}% Optimal`;

    // 5. Performance Summary Grid
    const sumTotalVehicles = document.getElementById("summaryTotalVehicles");
    const sumAvgVehicles = document.getElementById("summaryAvgVehicles");
    const sumGreenTimes = document.getElementById("summaryGreenTimes");
    const sumFixedWait = document.getElementById("summaryFixedWait");
    const sumAdaptiveWait = document.getElementById("summaryAdaptiveWait");
    const sumWaitReduction = document.getElementById("summaryWaitReduction");
    const sumBadge = document.getElementById("summaryWaitReductionBadge");

    if (sumTotalVehicles) sumTotalVehicles.textContent = (hasAnalyzed || isSimMode) ? data.total_vehicles : "—";
    if (sumAvgVehicles) {
        const avg = (hasAnalyzed || isSimMode) ? (data.total_vehicles / 4).toFixed(1) : "—";
        sumAvgVehicles.textContent = avg;
    }
    if (sumGreenTimes) {
        sumGreenTimes.textContent = `${data.roads.north?.green_time || 0} / ${data.roads.south?.green_time || 0} / ${data.roads.east?.green_time || 0} / ${data.roads.west?.green_time || 0} s`;
    }
    if (sumFixedWait) sumFixedWait.textContent = comp.fixed_avg_wait_sec != null ? `${comp.fixed_avg_wait_sec.toFixed(1)}s` : "--s";
    if (sumAdaptiveWait) sumAdaptiveWait.textContent = comp.adaptive_avg_wait_sec != null ? `${comp.adaptive_avg_wait_sec.toFixed(1)}s` : "--s";
    if (sumWaitReduction) sumWaitReduction.textContent = `${waitRedPct}%`;
    if (sumBadge) sumBadge.textContent = `${waitRedPct}% Delay Saved`;

    // 6. Update Chart.js Visualizations
    updateCharts(data);

    // 7. Update Real-Time Signal HUD Service Sequence
    updateHUDServiceSequence(data.order);

    // 8. Re-synchronize signal timing state machine with new computed timings
    applyNewSignalSchedule(data);

    // 9. Process event logs from server
    if (data.logs && Array.isArray(data.logs)) {
        data.logs.forEach(msg => {
            if (!loggedMessageSet.has(msg)) {
                loggedMessageSet.add(msg);
                let badge = "AI-VISION";
                if (msg.includes("🚨") || msg.includes("EMERGENCY")) badge = "EMERGENCY";
                else if (msg.includes("night") || msg.includes("NIGHT")) badge = "NIGHT-CV";
                else if (msg.includes("dusk") || msg.includes("DUSK") || msg.includes("low-light")) badge = "LOW-LIGHT";
                else if (msg.includes("Simulation")) badge = "OPTIMIZER";
                logEvent(badge, msg);
            }
        });
    }
}
'''

new_js = js[:idx1] + new_ui_section + js[idx2:]
with open("static/js/dashboard.js", "w", encoding="utf-8") as f:
    f.write(new_js)

print("DASHBOARD UI PATCHED SUCCESSFULLY")

