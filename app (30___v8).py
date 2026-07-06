import os
import sys
import json
import time
import socket
import threading
import asyncio
import numpy as np
import websockets
from http.server import SimpleHTTPRequestHandler
import socketserver

# Конфигурация серверов
HTTP_PORT = 8000
WS_PORT = 8765
CHUNK_SIZE = 1024

# Потокобезопасное хранилище для переданных в браузер частотных характеристик
latest_fft_data = {
    "device_name": "Ожидание аудио...",
    "bass": 0.0,
    "mid": 0.0,
    "treble": 0.0,
    "spectrum": [0.0] * 64
}
data_lock = threading.Lock()

# --- ВСТРОЕННЫЙ HTML5/WebGL2 ВИЗУАЛИЗАТОР (Three.js + Физический симулятор частиц) ---
HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NEXUS MONOLITH - Architectural 3D Audio Physics Engine</title>
    <style>
        :root {
            --accent: #ffaa33;
            --accent-glow: rgba(255, 170, 51, 0.35);
            --bg-glass: rgba(12, 12, 16, 0.65);
            --border-glass: rgba(255, 255, 255, 0.05);
            --text-primary: #e0e0e5;
            --text-secondary: #8c8c9a;
        }
        
        body {
            margin: 0;
            overflow: hidden;
            background: #050507;
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
            color: var(--text-primary);
            user-select: none;
            -webkit-user-select: none;
        }
        
        canvas {
            display: block;
            width: 100vw;
            height: 100vh;
            position: absolute;
            top: 0;
            left: 0;
            z-index: 1;
        }

        /* Глассморфизм-панель управления */
        .glass-panel {
            background: var(--bg-glass);
            backdrop-filter: blur(25px) saturate(140%);
            -webkit-backdrop-filter: blur(25px) saturate(140%);
            border: 1px solid var(--border-glass);
            border-radius: 14px;
            box-shadow: 0 16px 50px rgba(0, 0, 0, 0.8), 
                        inset 0 1px 1px rgba(255, 255, 255, 0.05);
            transition: opacity 0.5s cubic-bezier(0.16, 1, 0.3, 1), 
                        transform 0.5s cubic-bezier(0.16, 1, 0.3, 1);
        }

        /* Главная панель управления */
        #control-panel {
            position: fixed;
            bottom: 30px;
            left: 50%;
            transform: translate(-50%, 30px);
            width: 90%;
            max-width: 1000px;
            z-index: 10;
            padding: 24px 30px;
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 30px;
            opacity: 0;
            pointer-events: none;
        }

        #control-panel.visible {
            opacity: 1;
            transform: translate(-50%, 0);
            pointer-events: auto;
        }

        /* Информационный оверлей */
        #stats-overlay {
            position: fixed;
            top: 30px;
            left: 30px;
            z-index: 10;
            padding: 18px 24px;
            min-width: 220px;
            opacity: 0;
            pointer-events: none;
            transform: translateY(-20px);
        }

        #stats-overlay.visible {
            opacity: 1;
            transform: translateY(0);
            pointer-events: auto;
        }

        /* Вспомогательные подсказки */
        #instruction-tooltip {
            position: fixed;
            top: 30px;
            right: 30px;
            z-index: 10;
            padding: 10px 18px;
            font-size: 11px;
            letter-spacing: 0.5px;
            pointer-events: none;
            opacity: 0;
            transform: translateY(-20px);
            color: var(--text-secondary);
        }
        
        #instruction-tooltip.visible {
            opacity: 0.8;
            transform: translateY(0);
        }

        /* Текстовые элементы */
        .panel-title {
            font-size: 15px;
            font-weight: 800;
            letter-spacing: 2.5px;
            text-transform: uppercase;
            color: #fff;
            margin: 2px 0 8px 0; /* Уменьшен отступ для соответствия остальному UI */
            background: linear-gradient(45deg, #ffffff, var(--accent));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .panel-subtitle {
            font-size: 9px;
            color: var(--text-secondary);
            letter-spacing: 1.5px;
            text-transform: uppercase;
            margin: 0 0 12px 0;
            font-weight: 600;
            opacity: 0.7;
        }

        .section-title {
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 1.2px;
            text-transform: uppercase;
            color: var(--accent);
            margin: 0 0 16px 0;
            padding-bottom: 6px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .slider-container {
            display: flex;
            flex-direction: column;
            gap: 14px;
        }

        .control-group {
            display: flex;
            flex-direction: column;
            gap: 5px;
        }

        .control-label {
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            color: var(--text-secondary);
            font-weight: 500;
        }

        .control-val {
            color: var(--accent);
            font-weight: 700;
            text-shadow: 0 0 8px var(--accent-glow);
        }

        /* Стилизация ползунков */
        input[type="range"] {
            -webkit-appearance: none;
            width: 100%;
            height: 3px;
            background: rgba(255, 255, 255, 0.06);
            border-radius: 2px;
            outline: none;
            transition: background 0.2s;
        }

        input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            appearance: none;
            width: 11px;
            height: 11px;
            border-radius: 50%;
            background: #ffffff;
            box-shadow: 0 0 8px var(--accent-glow);
            cursor: pointer;
            transition: transform 0.1s, background-color 0.1s;
            border: 1.5px solid var(--accent);
        }

        input[type="range"]::-webkit-slider-thumb:hover {
            transform: scale(1.3);
            background: var(--accent);
        }

        /* Выпадающие списки */
        select {
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 6px;
            color: var(--text-primary);
            padding: 6px 12px;
            font-size: 11px;
            outline: none;
            cursor: pointer;
            transition: border-color 0.2s, background 0.2s;
            width: 100%;
            font-family: inherit;
        }

        select:hover, select:focus {
            border-color: var(--accent);
            background: rgba(255, 255, 255, 0.06);
        }

        select option {
            background: #0a0a0d;
            color: #fff;
        }

        /* Спектрометр и аудиоустройство */
        .audio-device-text {
            font-size: 11px;
            font-weight: 600;
            color: #ffffff;
            max-width: 240px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin-bottom: 16px; /* Оптимальный отступ до линеек эквалайзера */
            opacity: 0.85;
        }

        .mini-meters {
            display: flex;
            flex-direction: column;
            gap: 8px;
            margin-top: 19px;
        }

        .mini-meter {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
        }

        .mini-meter-label {
            font-size: 9px;
            text-transform: uppercase;
            color: var(--text-secondary);
            width: 50px;
            font-weight: 600;
        }

        .mini-meter-bg {
            flex-grow: 1;
            height: 4px;
            background: rgba(255, 255, 255, 0.04);
            border-radius: 2px;
            overflow: hidden;
            position: relative;
        }

        .mini-meter-fill {
            height: 100%;
            width: 0%;
            background: linear-gradient(90deg, var(--accent), #ffffff);
            border-radius: 2px;
            transition: width 0.08s ease-out;
        }

        /* Кастомный компактный тумблер в стиле остального интерфейса */
        .toggle-switch-container {
            display: flex;
            align-items: center;
            margin-top: 0;
        }

        .toggle-switch {
            position: relative;
            display: inline-block;
            width: 38px;
            height: 18px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 999px;
            cursor: pointer;
            box-shadow: inset 0 0 10px rgba(0, 0, 0, 0.22);
            transition: background-color 0.28s cubic-bezier(0.16, 1, 0.3, 1),
                        border-color 0.28s cubic-bezier(0.16, 1, 0.3, 1),
                        box-shadow 0.28s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .toggle-switch:hover {
            border-color: rgba(255, 255, 255, 0.18);
            background: rgba(255, 255, 255, 0.06);
        }

        .toggle-handle {
            position: absolute;
            top: 2px;
            left: 2px;
            width: 12px;
            height: 12px;
            background: rgba(255, 255, 255, 0.38);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 50%;
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.45);
            transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1),
                        background-color 0.28s cubic-bezier(0.16, 1, 0.3, 1),
                        box-shadow 0.28s cubic-bezier(0.16, 1, 0.3, 1);
        }

        /* Активное состояние тумблера */
        input[type="checkbox"]:checked + .toggle-switch {
            background: rgba(255, 170, 51, 0.13);
            border-color: var(--accent);
            box-shadow: inset 0 0 10px rgba(0, 0, 0, 0.2);
        }

        input[type="checkbox"]:checked + .toggle-switch .toggle-handle {
            transform: translateX(20px);
            background: var(--accent);
            border-color: rgba(255, 255, 255, 0.45);
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.45);
        }

        /* Адаптивность для мобильных экранов */
        @media (max-width: 800px) {
            #control-panel {
                grid-template-columns: 1fr;
                gap: 16px;
                padding: 16px;
                bottom: 10px;
                max-height: 50vh;
                overflow-y: auto;
            }
            #stats-overlay {
                top: 10px;
                left: 10px;
                padding: 12px;
            }
            #instruction-tooltip {
                display: none;
            }
        }
    </style>
</head>
<body>
    <canvas id="gl-canvas"></canvas>
    
    <!-- Всплывающий отладочный маркер для коллизий (показывает номер при наведении) -->
    <div id="debug-label" style="position: absolute; pointer-events: none; background: rgba(10, 10, 15, 0.9); color: var(--accent); padding: 5px 10px; border: 1px solid var(--accent); border-radius: 6px; font-family: monospace; font-size: 11px; z-index: 100; display: none; box-shadow: 0 0 10px var(--accent-glow); transition: opacity 0.15s ease;"></div>

    <!-- Диагностика и мини-эквалайзер -->
    <div id="stats-overlay" class="glass-panel">
        <div class="panel-title">MONOLITH CORE</div>
        <div class="audio-device-text" id="device-name" data-i18n="deviceWaiting">Waiting for audio...</div>
        
        <div class="mini-meters">
            <div class="mini-meter">
                <span class="mini-meter-label" data-i18n="meterBass">BASS</span>
                <div class="mini-meter-bg"><div class="mini-meter-fill" id="meter-bass"></div></div>
            </div>
            <div class="mini-meter">
                <span class="mini-meter-label" data-i18n="meterMid">MID</span>
                <div class="mini-meter-bg"><div class="mini-meter-fill" id="meter-mid"></div></div>
            </div>
            <div class="mini-meter">
                <span class="mini-meter-label" data-i18n="meterTreble">TREBLE</span>
                <div class="mini-meter-bg"><div class="mini-meter-fill" id="meter-treble"></div></div>
            </div>
        </div>
    </div>

    <!-- Интерактивная подсказка -->
    <div id="instruction-tooltip" class="glass-panel">
        <span data-i18n="instruction">Rotate the sphere with the left mouse button | Zoom with the wheel</span>
    </div>

    <!-- Главная панель управления -->
    <div id="control-panel" class="glass-panel">
        <!-- Столбец 1: Физика Притяжения и Завирений -->
        <div class="slider-container">
            <div class="section-title">
                <span data-i18n="sectionGravity">Gravity & Medium</span>
                <span style="font-size: 9px; opacity: 0.5;" data-i18n="tagPhysics">Physics</span>
            </div>
            
            <div class="control-group">
                <label class="control-label" data-i18n="themeLabel">Color Aesthetic</label>
                <select id="select-theme">
                    <option value="titanium" data-i18n="themeTitanium">Titanium & Amber (Industrial)</option>
                    <option value="copper" data-i18n="themeCopper">Patinated Copper (Steampunk)</option>
                    <option value="obsidian" selected data-i18n="themeObsidian">Obsidian & Alabaster (Minimalism)</option>
                    <option value="gold" data-i18n="themeGold">Old Gold & Smoke (Majestic)</option>
                    <option value="arctic" data-i18n="themeArctic">Arctic Neon (Cryo Lab)</option>
                    <option value="sakura" data-i18n="themeSakura">Sakura Steel (Neo Tokyo)</option>
                    <option value="emerald" data-i18n="themeEmerald">Emerald Circuit (Bio-Tech)</option>
                    <option value="crimson" data-i18n="themeCrimson">Crimson Carbon (Racing)</option>
                    <option value="violet" data-i18n="themeViolet">Violet Singularity (Cosmic)</option>
                    <option value="porcelain" data-i18n="themePorcelain">Porcelain & Cobalt (Gallery)</option>
                    <option value="abyss" data-i18n="themeAbyss">Abyssal Blue (Deep Sea)</option>
                    <option value="solar" data-i18n="themeSolar">Solar Flare (Sunset)</option>
                </select>
            </div>

            <div class="control-group">
                <label class="control-label" data-i18n="languageLabel">Language</label>
                <select id="select-language">
                    <option value="en" selected>English</option>
                    <option value="ru">Русский</option>
                    <option value="zh">中文</option>
                    <option value="hi">हिन्दी</option>
                    <option value="es">Español</option>
                </select>
            </div>

            <div class="control-group">
                <label class="control-label">
                    <span data-i18n="gravityCore">Core Gravity</span>
                    <span class="control-val" id="val-gravity">0.40</span>
                </label>
                <input type="range" id="slide-gravity" min="0.05" max="1.5" step="0.05" value="0.40">
            </div>

            <div class="control-group">
                <label class="control-label">
                    <span data-i18n="viscosity">Medium Viscosity (Jelly)</span>
                    <span class="control-val" id="val-viscosity">0.85</span>
                </label>
                <input type="range" id="slide-viscosity" min="0.1" max="2.5" step="0.05" value="0.85">
            </div>

            <div class="control-group">
                <label class="control-label">
                    <span data-i18n="turbulence">Air Turbulence</span>
                    <span class="control-val" id="val-turbulence">0.50</span>
                </label>
                <input type="range" id="slide-turbulence" min="0.0" max="2.0" step="0.05" value="0.50">
            </div>
        </div>

        <!-- Столбец 2: Механика Диффузоров -->
        <div class="slider-container">
            <div class="section-title">
                <span data-i18n="sectionDiffusers">Diffuser Behavior</span>
                <span style="font-size: 9px; opacity: 0.5;" data-i18n="tagActuators">Actuators</span>
            </div>

            <div class="control-group">
                <label class="control-label">
                    <span data-i18n="repulsion">Explosive Impact Force</span>
                    <span class="control-val" id="val-repulsion">3.50</span>
                </label>
                <input type="range" id="slide-repulsion" min="0.5" max="8.0" step="0.1" value="3.50">
            </div>

            <div class="control-group">
                <label class="control-label">
                    <span data-i18n="boomSens">“Boom” Sensitivity</span>
                    <span class="control-val" id="val-sens">1.10</span>
                </label>
                <input type="range" id="slide-sens" min="0.5" max="2.5" step="0.05" value="1.10">
            </div>

            <div class="control-group">
                <label class="control-label">
                    <span data-i18n="springReturn">Return Elasticity</span>
                    <span class="control-val" id="val-spring">20.0</span>
                </label>
                <input type="range" id="slide-spring" min="5.0" max="50.0" step="1.0" value="20.0">
            </div>

            <div class="control-group">
                <label class="control-label">
                    <span data-i18n="musicVibration">Music Vibration</span>
                    <span class="control-val" id="val-vibr">0.08</span>
                </label>
                <input type="range" id="slide-vibr" min="0.0" max="0.3" step="0.01" value="0.08">
            </div>

            <div class="control-group" style="margin-top: 10px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span class="control-label" data-i18n="visualizationToggle">Visualization</span>
                    <div class="toggle-switch-container">
                        <input type="checkbox" id="toggle-render-mode" checked style="display: none;">
                        <label for="toggle-render-mode" class="toggle-switch" title="Enable / disable rendering" data-i18n-title="toggleTitle">
                            <span class="toggle-handle"></span>
                        </label>
                    </div>
                </div>
            </div>
        </div>

        <!-- Столбец 3: Камера и Свечение -->
        <div class="slider-container">
            <div class="section-title">
                <span data-i18n="sectionRendering">Rendering & Camera</span>
                <span style="font-size: 9px; opacity: 0.5;" data-i18n="tagRendering">Rendering</span>
            </div>

            <div class="control-group">
                <label class="control-label">
                    <span data-i18n="bloom">Atmospheric Glow</span>
                    <span class="control-val" id="val-bloom">0.80</span>
                </label>
                <input type="range" id="slide-bloom" min="0.0" max="3.0" step="0.05" value="0.80">
            </div>

            <div class="control-group">
                <label class="control-label">
                    <span data-i18n="bloomRadius">Scattering Radius</span>
                    <span class="control-val" id="val-radius">0.50</span>
                </label>
                <input type="range" id="slide-radius" min="0.1" max="1.5" step="0.05" value="0.50">
            </div>

            <div class="control-group">
                <label class="control-label">
                    <span data-i18n="screenShake">Screen Shake</span>
                    <span class="control-val" id="val-shake">0.35</span>
                </label>
                <input type="range" id="slide-shake" min="0.0" max="1.5" step="0.05" value="0.35">
            </div>

            <div class="control-group">
                <label class="control-label">
                    <span data-i18n="cameraOrbit">Camera Orbit</span>
                    <span class="control-val" id="val-cam-rot">0.15</span>
                </label>
                <input type="range" id="slide-cam-rot" min="0.0" max="1.0" step="0.02" value="0.15">
            </div>

            <div class="control-group">
                <label class="control-label" data-i18n="trajectoryLabel">Camera Trajectory</label>
                <select id="select-trajectory">
                    <option value="nonCyclic" data-i18n="trajectoryNonCyclic">Non-cyclic drift</option>
                    <option value="classic" selected data-i18n="trajectoryClassic">Classic loop</option>
                </select>
            </div>

            <div class="control-group">
                <label class="control-label" data-i18n="antialiasing">Antialiasing</label>
                <select id="select-antialiasing">
                    <option value="off" data-i18n="aaOff">Off (faster)</option>
                    <option value="fxaa" data-i18n="aaFxaa">FXAA (fast)</option>
                    <option value="smaa" data-i18n="aaSmaa">SMAA (quality)</option>
                    <option value="ssaa15">SSAA 1.5×</option>
                    <option value="ssaa2" selected>SSAA 2×</option>
                    <option value="ssaa4">SSAA 4×</option>
                    <option value="ssaa8">SSAA 8×</option>
                </select>
            </div>
        </div>

    </div>

    <!-- Загрузка скриптов Three.js и Пост-процессинга -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    
    <!-- Постпроцессинг для кинематографичного свечения (Unreal Bloom) -->
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/postprocessing/EffectComposer.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/postprocessing/ShaderPass.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/postprocessing/RenderPass.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/shaders/CopyShader.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/shaders/LuminosityHighPassShader.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/shaders/FXAAShader.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/shaders/SMAAShader.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/postprocessing/UnrealBloomPass.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/postprocessing/SMAAPass.js"></script>

    <script>
        // --- Физические и визуальные параметры по умолчанию ---
        const config = {
            gravityStrength: 0.40,      // Тяга к ядру
            viscosity: 0.85,            // Торможение в воздухе (эффект желе)
            turbulence: 0.50,           // Сила случайных воздушных завихрений
            repulsionForce: 3.50,       // Мощность выталкивания воздуха диффузорами
            sensToBoom: 1.10,           // Коэффициент чувствительности к "бум" ударам
            springConstant: 20.0,       // Жесткость пружины возврата диффузора
            springDamping: 5.5,         // Затухание колебаний пружины диффузора
            vibrationAmp: 0.08,         // Постоянное дрожание от средних частот
            bloomIntensity: 0.80,       // Интенсивность рассеянного свечения
            bloomRadius: 0.50,          // Радиус свечения
            screenShake: 0.35,          // Мощность вибрации кадра на ударах
            cameraRotationSpeed: 0.15,  // Скорость вращения монолита
            rotationTrajectory: "classic", // nonCyclic — неповторяющаяся, classic — старая 3:1
            activeTheme: "obsidian",
            antialiasing: "ssaa2",      // off / fxaa / smaa / ssaa15 / ssaa2 / ssaa4 / ssaa8
            debugObjectLabels: false,    // true — считать raycast и показывать ID объектов при наведении
            blastRadius: 3.8            // Максимальный радиус воздушной волны
        };

        const ROTATION_TRAJECTORIES = {
            // Похожа на старую траекторию, но отношение осей иррациональное: полного видимого цикла нет.
            nonCyclic: { y: 0.15, x: 0.05 * Math.sqrt(1.03) },
            // В точности прежняя траектория: Y:X = 3:1, полный повтор ориентации после 1 оборота X и 3 оборотов Y.
            classic: { y: 0.15, x: 0.05 }
        };

        let currentLang = "en";

        const I18N = {
            en: {
                deviceWaiting: "Waiting for audio...",
                deviceConnecting: "Connecting to server...",
                meterBass: "BASS",
                meterMid: "MID",
                meterTreble: "TREBLE",
                instruction: "Rotate the sphere with the left mouse button | Zoom with the wheel",
                languageLabel: "Language",
                trajectoryLabel: "Sphere Trajectory",
                trajectoryNonCyclic: "Non-cyclic drift",
                trajectoryClassic: "Classic loop",
                sectionGravity: "Gravity & Medium",
                tagPhysics: "Physics",
                themeLabel: "Color Aesthetic",
                themeTitanium: "Titanium & Amber (Industrial)",
                themeCopper: "Patinated Copper (Steampunk)",
                themeObsidian: "Obsidian & Alabaster (Minimalism)",
                themeGold: "Old Gold & Smoke (Majestic)",
                themeArctic: "Arctic Neon (Cryo Lab)",
                themeSakura: "Sakura Steel (Neo Tokyo)",
                themeEmerald: "Emerald Circuit (Bio-Tech)",
                themeCrimson: "Crimson Carbon (Racing)",
                themeViolet: "Violet Singularity (Cosmic)",
                themePorcelain: "Porcelain & Cobalt (Gallery)",
                themeAbyss: "Abyssal Blue (Deep Sea)",
                themeSolar: "Solar Flare (Sunset)",
                gravityCore: "Core Gravity",
                viscosity: "Medium Viscosity (Jelly)",
                turbulence: "Air Turbulence",
                sectionDiffusers: "Diffuser Behavior",
                tagActuators: "Actuators",
                repulsion: "Explosive Impact Force",
                boomSens: "“Boom” Sensitivity",
                springReturn: "Return Elasticity",
                musicVibration: "Music Vibration",
                sectionRendering: "Rendering & Sphere",
                tagRendering: "Rendering",
                bloom: "Atmospheric Glow",
                bloomRadius: "Scattering Radius",
                screenShake: "Screen Shake",
                cameraOrbit: "Sphere Rotation Speed",
                visualizationToggle: "Visualization",
                toggleTitle: "Enable / disable rendering",
                antialiasing: "Antialiasing",
                aaOff: "Off (faster)",
                aaFxaa: "FXAA (fast)",
                aaSmaa: "SMAA (quality)"
            },
            ru: {
                deviceWaiting: "Ожидание аудио...",
                deviceConnecting: "Подключение к серверу...",
                meterBass: "БАС",
                meterMid: "СЕРЕД.",
                meterTreble: "ВЧ",
                instruction: "Вращайте сферу левой кнопкой мыши | Масштабируйте колесиком",
                languageLabel: "Язык",
                trajectoryLabel: "Траектория сферы",
                trajectoryNonCyclic: "Незацикленный дрейф",
                trajectoryClassic: "Классический цикл",
                sectionGravity: "Гравитация и Среда",
                tagPhysics: "Физика",
                themeLabel: "Цветовая Эстетика",
                themeTitanium: "Титан и Янтарь (Индустриальный)",
                themeCopper: "Патинированная Медь (Стимпанк)",
                themeObsidian: "Обсидиан и Алебастр (Минимализм)",
                themeGold: "Старое Золото и Дым (Величественный)",
                themeArctic: "Арктический Неон (Крио-лаборатория)",
                themeSakura: "Сталь Сакуры (Нео-Токио)",
                themeEmerald: "Изумрудная Схема (Био-тех)",
                themeCrimson: "Багровый Карбон (Гоночный)",
                themeViolet: "Фиолетовая Сингулярность (Космос)",
                themePorcelain: "Фарфор и Кобальт (Галерея)",
                themeAbyss: "Бездонная Синева (Глубины)",
                themeSolar: "Солнечная Вспышка (Закат)",
                gravityCore: "Гравитация Ядра",
                viscosity: "Вязкость Среды (Желе)",
                turbulence: "Завихрения воздуха",
                sectionDiffusers: "Поведение Диффузоров",
                tagActuators: "Актуаторы",
                repulsion: "Взрывная сила удара",
                boomSens: "Чувствительность к «Бум»",
                springReturn: "Упругость возврата",
                musicVibration: "Вибрация при музыке",
                sectionRendering: "Рендеринг и Сфера",
                tagRendering: "Рендеринг",
                bloom: "Свечение атмосферы",
                bloomRadius: "Радиус рассеивания",
                screenShake: "Дрожание экрана",
                cameraOrbit: "Скорость вращения сферы",
                visualizationToggle: "Включение визуализации",
                toggleTitle: "Включить / выключить рендеринг",
                antialiasing: "Антиалиасинг",
                aaOff: "Выкл. (быстрее)",
                aaFxaa: "FXAA (быстрый)",
                aaSmaa: "SMAA (качественный)"
            },
            zh: {
                deviceWaiting: "等待音频...",
                deviceConnecting: "正在连接服务器...",
                meterBass: "低音",
                meterMid: "中音",
                meterTreble: "高音",
                instruction: "按住鼠标左键旋转球体 | 使用滚轮缩放",
                languageLabel: "语言",
                trajectoryLabel: "球体轨迹",
                trajectoryNonCyclic: "非循环漂移",
                trajectoryClassic: "经典循环",
                sectionGravity: "引力与介质",
                tagPhysics: "物理",
                themeLabel: "色彩风格",
                themeTitanium: "钛金与琥珀（工业）",
                themeCopper: "铜绿铜色（蒸汽朋克）",
                themeObsidian: "黑曜石与雪花石（极简）",
                themeGold: "旧金与烟雾（宏伟）",
                themeArctic: "北极霓虹（低温实验室）",
                themeSakura: "樱花钢铁（新东京）",
                themeEmerald: "翡翠电路（生物科技）",
                themeCrimson: "绯红碳纤（竞速）",
                themeViolet: "紫色奇点（宇宙）",
                themePorcelain: "瓷白与钴蓝（画廊）",
                themeAbyss: "深渊蓝（深海）",
                themeSolar: "太阳耀斑（日落）",
                gravityCore: "核心引力",
                viscosity: "介质黏度（果冻）",
                turbulence: "空气涡流",
                sectionDiffusers: "振膜行为",
                tagActuators: "执行器",
                repulsion: "爆发冲击力",
                boomSens: "“轰击”灵敏度",
                springReturn: "回弹弹性",
                musicVibration: "音乐振动",
                sectionRendering: "渲染与球体",
                tagRendering: "渲染",
                bloom: "氛围辉光",
                bloomRadius: "散射半径",
                screenShake: "屏幕震动",
                cameraOrbit: "球体旋转速度",
                visualizationToggle: "可视化",
                toggleTitle: "启用 / 禁用渲染",
                antialiasing: "抗锯齿",
                aaOff: "关闭（更快）",
                aaFxaa: "FXAA（快速）",
                aaSmaa: "SMAA（高质量）"
            },
            hi: {
                deviceWaiting: "ऑडियो की प्रतीक्षा...",
                deviceConnecting: "सर्वर से जुड़ रहा है...",
                meterBass: "बास",
                meterMid: "मिड",
                meterTreble: "ट्रेबल",
                instruction: "बाएँ माउस बटन से गोला घुमाएँ | व्हील से ज़ूम करें",
                languageLabel: "भाषा",
                trajectoryLabel: "गोले के प्रक्षेपवक्र",
                trajectoryNonCyclic: "गैर-चक्रीय बहाव",
                trajectoryClassic: "क्लासिक चक्र",
                sectionGravity: "गुरुत्व और माध्यम",
                tagPhysics: "भौतिकी",
                themeLabel: "रंग शैली",
                themeTitanium: "टाइटेनियम और एम्बर (औद्योगिक)",
                themeCopper: "पैटिना कॉपर (स्टीमपंक)",
                themeObsidian: "ओब्सिडियन और अलबास्टर (मिनिमल)",
                themeGold: "पुराना सोना और धुआँ (भव्य)",
                themeArctic: "आर्कटिक निऑन (क्रायो लैब)",
                themeSakura: "सкуरा स्टील (नियो टोक्यो)",
                themeEmerald: "एमराल्ड सर्किट (बायो-टेक)",
                themeCrimson: "क्रिमसन कार्बन (रेसिंग)",
                themeViolet: "वायलेट सिंगुलैरिटी (कॉस्मिक)",
                themePorcelain: "पोर्सिलेन और कोबाल्ट (गैलरी)",
                themeAbyss: "अथाह नीला (गहरा समुद्र)",
                themeSolar: "सोलर फ्लेयर (सूर्यास्त)",
                gravityCore: "कोर गुरुत्व",
                viscosity: "माध्यम श्यानता (जेली)",
                turbulence: "हवा के भंवर",
                sectionDiffusers: "डिफ्यूज़र व्यवहार",
                tagActuators: "ऐक्चुएटर",
                repulsion: "विस्फोटक आघात बल",
                boomSens: "“बूम” संवेदनशीलता",
                springReturn: "वापसी लोच",
                musicVibration: "संगीत कंपन",
                sectionRendering: "रेंडरिंग और गोला",
                tagRendering: "रेंडरिंग",
                bloom: "वातावरण चमक",
                bloomRadius: "प्रकीर्णन त्रिज्या",
                screenShake: "स्क्रीन कंपन",
                cameraOrbit: "गोले के घूमने की गति",
                visualizationToggle: "विज़ुअलाइज़ेशन",
                toggleTitle: "रेंडरिंग चालू / बंद करें",
                antialiasing: "एंटी-अलायसिंग",
                aaOff: "बंद (तेज़)",
                aaFxaa: "FXAA (तेज़)",
                aaSmaa: "SMAA (गुणवत्ता)"
            },
            es: {
                deviceWaiting: "Esperando audio...",
                deviceConnecting: "Conectando al servidor...",
                meterBass: "BAJOS",
                meterMid: "MEDIOS",
                meterTreble: "AGUDOS",
                instruction: "Gira la esfera con el botón izquierdo | Haz zoom con la rueda",
                languageLabel: "Idioma",
                trajectoryLabel: "Trayectoria de la esfera",
                trajectoryNonCyclic: "Deriva no cíclica",
                trajectoryClassic: "Bucle clásico",
                sectionGravity: "Gravedad y Medio",
                tagPhysics: "Física",
                themeLabel: "Estética de Color",
                themeTitanium: "Titanio y Ámbar (Industrial)",
                themeCopper: "Cobre Patinado (Steampunk)",
                themeObsidian: "Obsidiana y Alabastro (Minimalismo)",
                themeGold: "Oro Viejo y Humo (Majestuoso)",
                themeArctic: "Neón Ártico (Laboratorio Crio)",
                themeSakura: "Acero Sakura (Neo Tokio)",
                themeEmerald: "Circuito Esmeralda (Bio-Tech)",
                themeCrimson: "Carbono Carmesí (Carreras)",
                themeViolet: "Singularidad Violeta (Cósmica)",
                themePorcelain: "Porcelana y Cobalto (Galería)",
                themeAbyss: "Azul Abisal (Mar Profundo)",
                themeSolar: "Llamarada Solar (Atardecer)",
                gravityCore: "Gravedad del Núcleo",
                viscosity: "Viscosidad del Medio (Gelatina)",
                turbulence: "Turbulencia de Aire",
                sectionDiffusers: "Comportamiento de Difusores",
                tagActuators: "Actuadores",
                repulsion: "Fuerza de Impacto Explosiva",
                boomSens: "Sensibilidad al “Boom”",
                springReturn: "Elasticidad de Retorno",
                musicVibration: "Vibración con Música",
                sectionRendering: "Renderizado y Esfera",
                tagRendering: "Renderizado",
                bloom: "Resplandor Atmosférico",
                bloomRadius: "Radio de Dispersión",
                screenShake: "Sacudida de Pantalla",
                cameraOrbit: "Velocidad de rotación de la esfera",
                visualizationToggle: "Visualización",
                toggleTitle: "Activar / desactivar renderizado",
                antialiasing: "Antialiasing",
                aaOff: "Desactivado (más rápido)",
                aaFxaa: "FXAA (rápido)",
                aaSmaa: "SMAA (calidad)"
            }
        };

        function t(key) {
            return (I18N[currentLang] && I18N[currentLang][key]) || I18N.en[key] || key;
        }

        function localizeDeviceName(name) {
            if (!name || name === "Ожидание аудио..." || name === "Waiting for audio..." || name === "等待音频..." || name === "ऑडियो की प्रतीक्षा..." || name === "Esperando audio...") {
                return t('deviceWaiting');
            }
            if (name === "Подключение к серверу..." || name === "Connecting to server..." || name === "正在连接服务器..." || name === "सर्वर से जुड़ रहा है..." || name === "Conectando al servidor...") {
                return t('deviceConnecting');
            }
            return name;
        }

        function applyLocalization(lang) {
            currentLang = I18N[lang] ? lang : "en";
            document.documentElement.lang = currentLang;
            document.querySelectorAll('[data-i18n]').forEach(el => {
                el.textContent = t(el.dataset.i18n);
            });
            document.querySelectorAll('[data-i18n-title]').forEach(el => {
                el.title = t(el.dataset.i18nTitle);
            });
            if (deviceNameEl) deviceNameEl.textContent = localizeDeviceName(rawData.device_name);
        }

        const PALETTES = {
            titanium: {
                name: "Титан и Янтарь",
                bg: 0x07070a,
                accent: "#ffaa33",
                accentGlow: "rgba(255, 170, 51, 0.35)",
                monolithColor: 0x1d2025,
                monolithRoughness: 0.35,
                monolithMetalness: 0.9,
                frameColor: 0x473c33,
                dustColor: 0xffebd4,
                windowGlow: 0xffaa44
            },
            copper: {
                name: "Патинированная Медь",
                bg: 0x060808,
                accent: "#33ffd2",
                accentGlow: "rgba(51, 255, 210, 0.35)",
                monolithColor: 0x241a15,
                monolithRoughness: 0.45,
                monolithMetalness: 0.85,
                frameColor: 0x1e2528,
                dustColor: 0xd9fff7,
                windowGlow: 0x22ffd0
            },
            obsidian: {
                name: "Обсидиан и Алебастр",
                bg: 0x040405,
                accent: "#ffffff",
                accentGlow: "rgba(255, 255, 255, 0.25)",
                monolithColor: 0x0d0d0f,
                monolithRoughness: 0.08,
                monolithMetalness: 0.1,
                frameColor: 0x1c1c1f,
                dustColor: 0xffffff,
                windowGlow: 0xffffff
            },
            gold: {
                name: "Старое Золото и Дым",
                bg: 0x080705,
                accent: "#ffdd77",
                accentGlow: "rgba(255, 221, 119, 0.35)",
                monolithColor: 0x2b2214,
                monolithRoughness: 0.30,
                monolithMetalness: 0.95,
                frameColor: 0x1c1c1a,
                dustColor: 0xffeebb,
                windowGlow: 0xffbb55
            },
            arctic: {
                name: "Арктический Неон",
                bg: 0x021018,
                accent: "#5fe7ff",
                accentGlow: "rgba(95, 231, 255, 0.36)",
                monolithColor: 0x172a33,
                monolithRoughness: 0.22,
                monolithMetalness: 0.78,
                frameColor: 0xd8f7ff,
                dustColor: 0xbff6ff,
                windowGlow: 0x76f2ff
            },
            sakura: {
                name: "Сталь Сакуры",
                bg: 0x120711,
                accent: "#ff79c6",
                accentGlow: "rgba(255, 121, 198, 0.35)",
                monolithColor: 0x231924,
                monolithRoughness: 0.26,
                monolithMetalness: 0.82,
                frameColor: 0x2d2430,
                dustColor: 0xffd6ef,
                windowGlow: 0xff4fb8
            },
            emerald: {
                name: "Изумрудная Схема",
                bg: 0x020d08,
                accent: "#2dff88",
                accentGlow: "rgba(45, 255, 136, 0.34)",
                monolithColor: 0x0d2418,
                monolithRoughness: 0.38,
                monolithMetalness: 0.72,
                frameColor: 0x06140e,
                dustColor: 0xc8ffe0,
                windowGlow: 0x29ff7a
            },
            crimson: {
                name: "Багровый Карбон",
                bg: 0x0b0203,
                accent: "#ff243f",
                accentGlow: "rgba(255, 36, 63, 0.34)",
                monolithColor: 0x151517,
                monolithRoughness: 0.18,
                monolithMetalness: 0.88,
                frameColor: 0x070708,
                dustColor: 0xffb3bd,
                windowGlow: 0xff1734
            },
            violet: {
                name: "Фиолетовая Сингулярность",
                bg: 0x070314,
                accent: "#9b5cff",
                accentGlow: "rgba(155, 92, 255, 0.36)",
                monolithColor: 0x120b24,
                monolithRoughness: 0.16,
                monolithMetalness: 0.86,
                frameColor: 0x080510,
                dustColor: 0xe1d2ff,
                windowGlow: 0xb46cff
            },
            porcelain: {
                name: "Фарфор и Кобальт",
                bg: 0x0b0f16,
                accent: "#2f6dff",
                accentGlow: "rgba(47, 109, 255, 0.34)",
                monolithColor: 0xe7e2d6,
                monolithRoughness: 0.52,
                monolithMetalness: 0.18,
                frameColor: 0x1b2f66,
                dustColor: 0xffffff,
                windowGlow: 0x346dff
            },
            abyss: {
                name: "Бездонная Синева",
                bg: 0x000713,
                accent: "#00a6ff",
                accentGlow: "rgba(0, 166, 255, 0.34)",
                monolithColor: 0x031b2a,
                monolithRoughness: 0.42,
                monolithMetalness: 0.64,
                frameColor: 0x020914,
                dustColor: 0xb7e9ff,
                windowGlow: 0x00c3ff
            },
            solar: {
                name: "Солнечная Вспышка",
                bg: 0x140603,
                accent: "#ff6a1a",
                accentGlow: "rgba(255, 106, 26, 0.36)",
                monolithColor: 0x302016,
                monolithRoughness: 0.34,
                monolithMetalness: 0.82,
                frameColor: 0x1b0a05,
                dustColor: 0xffd3a3,
                windowGlow: 0xff8a1c
            }
        };

        // --- Состояние аудио ---
        let rawData = { bass: 0, mid: 0, treble: 0, spectrum: Array(64).fill(0), device_name: "Waiting for audio..." };
        let smoothData = { bass: 0, mid: 0, treble: 0, spectrum: Array(64).fill(0) };
        let uiSmooth = { bass: 0, mid: 0, treble: 0 }; // Отдельное сглаживание для интерфейса

        // --- Инициализация WebGL ---
        const canvas = document.getElementById('gl-canvas');
        const scene = new THREE.Scene();

        // Камера
        const camera = new THREE.PerspectiveCamera(40, window.innerWidth / window.innerHeight, 0.1, 100);
        camera.position.set(0, 1.8, 9.0);

        const renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: false, powerPreference: "high-performance" });
        renderer.setSize(window.innerWidth, window.innerHeight);
        renderer.setPixelRatio(1);
        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 1.05;

        // Интерактивное управление камерой
        const controls = new THREE.OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.05;
        controls.minDistance = 4.0;
        controls.maxDistance = 16.0;

        // --- Кастомный Шейдерный Глубокий Задний Фон ---
        const bgShaderMaterial = new THREE.ShaderMaterial({
            uniforms: {
                time: { value: 0 },
                color1: { value: new THREE.Color(0x060609) },
                color2: { value: new THREE.Color(0x010102) }
            },
            vertexShader: `
                varying vec2 vUv;
                void main() {
                    vUv = uv;
                    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
                }
            `,
            fragmentShader: `
                uniform float time;
                uniform vec3 color1;
                uniform vec3 color2;
                varying vec2 vUv;
                
                void main() {
                    float dist = distance(vUv, vec2(0.5));
                    // Элегантное виньетирование глубокого космоса
                    vec3 base = mix(color1, color2, smoothstep(0.2, 0.85, dist));
                    // Медленные структурные волны туманности
                    float wave = sin(vUv.x * 5.0 + time * 0.04) * cos(vUv.y * 4.0 - time * 0.03) * 0.004;
                    base += vec3(wave);
                    gl_FragColor = vec4(base, 1.0);
                }
            `,
            side: THREE.BackSide,
            depthWrite: false
        });

        const bgMesh = new THREE.Mesh(new THREE.SphereGeometry(22, 32, 32), bgShaderMaterial);
        scene.add(bgMesh);

        // Главная группа для вращения
        const visualizerGroup = new THREE.Group();
        scene.add(visualizerGroup);

        // --- Архитектурное Освещение ---
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.08);
        scene.add(ambientLight);

        // Мягкий рассеянный заполняющий свет
        const fillLight = new THREE.DirectionalLight(0xd9efff, 0.4);
        fillLight.position.set(-8, 4, 3);
        scene.add(fillLight);

        // Драматический прожектор с тенями, выявляющий текстуру строения
        const keyLight = new THREE.DirectionalLight(0xfff3e0, 1.2);
        keyLight.position.set(7, 12, 8);
        keyLight.castShadow = true;
        keyLight.shadow.mapSize.width = 1536;
        keyLight.shadow.mapSize.height = 1536;
        keyLight.shadow.bias = -0.0005;
        scene.add(keyLight);

        // --- СОЗДАНИЕ АНТРОПОГЕННОЙ СФЕРЫ-МОНОЛИТА ---
        const monolithGroup = new THREE.Group();
        visualizerGroup.add(monolithGroup);

        // 1. Основное прочное тело сферы
        const mainBodyGeo = new THREE.IcosahedronGeometry(1.8, 5);
        const mainBodyMat = new THREE.MeshStandardMaterial({
            color: 0x1d2025,
            roughness: 0.35,
            metalness: 0.9,
        });

        // Инжектируем кастомный вершинный и фрагментный GLSL-код для вырезания честных отверстий в сфере!
        // Это полностью убирает эффект пересечения текстур (клиппинг) диффузоров со сферой.
        mainBodyMat.onBeforeCompile = (shader) => {
            // Передаем координаты всех 13 колонок и радиус отверстия
            shader.uniforms.diffPositions = { value: diffusers.map(d => d.basePos) };
            shader.uniforms.holeRadius = { value: 0.275 };

            // Внедряем локальные координаты во фрагментный шейдер
            shader.vertexShader = 'varying vec3 vLocPos;\\n' + shader.vertexShader;
            shader.vertexShader = shader.vertexShader.replace(
                '#include <begin_vertex>',
                '#include <begin_vertex>\\nvLocPos = position;'
            );

            shader.fragmentShader = 'varying vec3 vLocPos;\\nuniform vec3 diffPositions[13];\\nuniform float holeRadius;\\n' + shader.fragmentShader;
            shader.fragmentShader = shader.fragmentShader.replace(
                'void main() {',
                `void main() {
                    // Вырезаем идеально круглые отверстия в местах стыка колонок со сферой в локальных координатах
                    for (int i = 0; i < 13; i++) {
                        if (distance(vLocPos, diffPositions[i]) < holeRadius) {
                            discard;
                        }
                    }
                `
            );
        };

        const mainBodyMesh = new THREE.Mesh(mainBodyGeo, mainBodyMat);
        mainBodyMesh.castShadow = true;
        mainBodyMesh.receiveShadow = true;
        monolithGroup.add(mainBodyMesh);

        // Детерминированный генератор псевдослучайных чисел с фиксированным сидом (убирает случайность генерации)
        let mathSeed = 45678;
        function seededRandom() {
            const x = Math.sin(mathSeed++) * 10000;
            return x - Math.floor(x);
        }

        // Вспомогательная функция детерминированных фиксированных координат на сфере
        function getRandomSpherePos(radius) {
            const u = seededRandom();
            const v = seededRandom();
            const theta = u * 2.0 * Math.PI;
            const phi = Math.acos(2.0 * v - 1.0);
            return new THREE.Vector3(
                Math.cos(theta) * Math.sin(phi) * radius,
                Math.sin(theta) * Math.sin(phi) * radius,
                Math.cos(phi) * radius
            );
        }

        // --- СОЗДАНИЕ ДИФФУЗОРОВ-ДИНАМИКОВ (Создаем сначала, чтобы избежать наложений) ---
        const diffusers = [];
        const diffCount = 14;

        // --- Параметры и функции для создания подвеса диффузора (Surround) ---
        // Подвес — это гибкое резиновое кольцо в форме полу-ролика (half-roll),
        // соединяющее внешний край диффузора с рамой динамика.
        // Один край закреплён на раме (неподвижный), другой — на краю диффузора (подвижный).
        // При движении диффузора наружу ролик распрямляется, при движении внутрь — сжимается.
        const SURROUND_RADIAL_SEGS = 32;  // Количество сегментов по окружности (как у конуса)
        const SURROUND_PROFILE_SEGS = 10; // Количество шагов профиля (от рамы до диффузора)

        // Создаём кольцевую геометрию подвеса с полу-роликовым профилем
        function createSurroundGeometry() {
            const geo = new THREE.BufferGeometry();
            const vertCount = (SURROUND_RADIAL_SEGS + 1) * (SURROUND_PROFILE_SEGS + 1);
            const positions = new Float32Array(vertCount * 3);
            const uvs = new Float32Array(vertCount * 2);

            // UV-координаты для текстурирования
            for (let j = 0; j <= SURROUND_RADIAL_SEGS; j++) {
                for (let i = 0; i <= SURROUND_PROFILE_SEGS; i++) {
                    const idx = j * (SURROUND_PROFILE_SEGS + 1) + i;
                    uvs[idx * 2] = j / SURROUND_RADIAL_SEGS;
                    uvs[idx * 2 + 1] = i / SURROUND_PROFILE_SEGS;
                }
            }

            // Индексы треугольников (два треугольника на каждый четырёхугольник)
            const indices = [];
            for (let j = 0; j < SURROUND_RADIAL_SEGS; j++) {
                for (let i = 0; i < SURROUND_PROFILE_SEGS; i++) {
                    const a = j * (SURROUND_PROFILE_SEGS + 1) + i;
                    const b = (j + 1) * (SURROUND_PROFILE_SEGS + 1) + i;
                    const c = (j + 1) * (SURROUND_PROFILE_SEGS + 1) + (i + 1);
                    const d = j * (SURROUND_PROFILE_SEGS + 1) + (i + 1);
                    indices.push(a, b, d);
                    indices.push(b, c, d);
                }
            }

            geo.setIndex(indices);
            geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
            geo.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));

            // Инициализация вершин в позиции покоя (displacement = 0)
            updateSurroundVertices(geo, 0);
            return geo;
        }

        // Обновляем вершины подвеса при смещении диффузора.
        // Подвес — это кольцевая поверхность между двумя окружностями:
        //   - Внешняя (неподвижная): крепится к внутреннему краю рамы динамика
        //   - Внутренняя (подвижная): крепится к внешнему краю диффузора (широкому раструбу)
        //
        // Расчёт профиля (поперечного сечения) подвеса:
        //   Параметр t идёт от 0 (край у рамы) до 1 (край у диффузора).
        //   Базовая позиция — линейная интерполяция между двумя точками крепления:
        //     r(t) = fixedR + (movingR - fixedR) * t
        //     y(t) = fixedY + (movingY - fixedY) * t
        //   Поверх этого линейного пути добавляется выпуклость полу-ролика:
        //     bulgeFactor = sin(π * t)  — максимален посередине, ноль на краях
        //     y += rollHeight * bulgeFactor            — основная выпуклость наружу (к зрителю)
        //     r += rollHeight * 0.2 * bulgeFactor      — небольшое радиальное расширение ролика
        //
        //   Высота ролика rollHeight адаптируется к степени сжатия/растяжения:
        //     - В покое: rollHeight = baseRollHeight (0.022)
        //     - При растяжении (диффузор наружу): rollHeight уменьшается (ролик распрямляется)
        //     - При сжатии (диффузор внутрь): rollHeight увеличивается (ролик сжимается)
        //     Формула: rollHeight = baseRollHeight * (restDist / currentDist)
        //     с ограничениями чтобы не было крайних значений.
        //
        //   Каждая вершина расположена по окружности:
        //     x = r * cos(angle),  z = r * sin(angle),  y = y
        function updateSurroundVertices(geo, displacement) {
            const positions = geo.attributes.position.array;

            // Неподвижная точка: внутренний край рамы (корпус динамика, фиксирован)
            const fixedR = 0.258;   // Внутренний радиус тора рамы (0.28 - 0.022)
            const fixedY = 0.0;     // Рама на y = 0

            // Подвижная точка: верх обода (rim) диффузора
            const movingR = 0.235;   // Радиус верха полутора rim (главный радиус rim)
            const movingY = 0.017 + displacement;  // Y-позиция верха rim с учётом смещения

            const dr = movingR - fixedR;  // Разница радиусов (≈ -0.023)
            const dy = movingY - fixedY;  // Разница по Y (≈ 0.017 + displacement)

            // Адаптивная высота полу-ролика
            const restDist = 0.0286;   // Расстояние между точками крепления в покое
            const currentDist = Math.max(0.008, Math.sqrt(dr * dr + dy * dy));
            const baseRollHeight = 0.022;
            const rollHeight = baseRollHeight * Math.min(2.5, Math.max(0.25, restDist / currentDist));

            for (let j = 0; j <= SURROUND_RADIAL_SEGS; j++) {
                const angle = (2.0 * Math.PI * j) / SURROUND_RADIAL_SEGS;
                const cosA = Math.cos(angle);
                const sinA = Math.sin(angle);

                for (let i = 0; i <= SURROUND_PROFILE_SEGS; i++) {
                    const t = i / SURROUND_PROFILE_SEGS;
                    const idx = j * (SURROUND_PROFILE_SEGS + 1) + i;

                    // Линейная интерполяция между точками крепления
                    let r = fixedR + dr * t;
                    let y = fixedY + dy * t;

                    // Выпуклость полу-ролика (максимум посередине, ноль на краях)
                    const bulgeFactor = Math.sin(Math.PI * t);
                    y += rollHeight * bulgeFactor;           // Основная выпуклость наружу (+Y)
                    r += rollHeight * 0.2 * bulgeFactor;     // Небольшое радиальное расширение

                    positions[idx * 3] = r * cosA;
                    positions[idx * 3 + 1] = y;
                    positions[idx * 3 + 2] = r * sinA;
                }
            }

            geo.attributes.position.needsUpdate = true;
            geo.computeVertexNormals();
        }

        function createDiffuserMesh() {
            const group = new THREE.Group();
            
            // 1. Внутреннее металлическое кольцо рамы (корпус динамика)
            const frameGeo = new THREE.TorusGeometry(0.28, 0.022, 12, 32);
            const frameMat = new THREE.MeshStandardMaterial({
                color: 0x473c33,
                metalness: 0.9,
                roughness: 0.22
            });
            const frame = new THREE.Mesh(frameGeo, frameMat);
            frame.rotation.x = Math.PI / 2; // укладываем на плоскость
            frame.castShadow = true;
            group.add(frame);

            // 2. Эластичный резиновый подвес (surround) — полу-ролик между рамой и ободом (rim) диффузора
            // Внешний край закреплён на раме (неподвижный), внутренний — на ободе/rim диффузора (подвижный).
            // При движении диффузора подвес растягивается/сжимается как резина, сохраняя герметичность.
            // Геометрия обновляется каждый кадр функцией updateSurroundVertices().
            const surroundGeo = createSurroundGeometry();
            const surroundMat = new THREE.MeshStandardMaterial({
                color: 0x0d0d10,
                roughness: 0.92,
                metalness: 0.02,
                side: THREE.DoubleSide
            });
            const surround = new THREE.Mesh(surroundGeo, surroundMat);
            surround.name = "surround";
            surround.castShadow = true;
            group.add(surround);
            
            // 3. Диффузорный конус (подвижная часть)
            // Вершина конуса направлена внутрь (узкая часть 0.08 внизу), широкий раструб (0.22) — наружу
            // Внешний радиус уменьшен до 0.22 для размещения обода (rim) между конусом и подвеской
            const coneGeo = new THREE.CylinderGeometry(0.22, 0.08, 0.132, 32, 1, true);
            const coneMat = new THREE.MeshStandardMaterial({
                color: 0x111113,
                metalness: 0.1,
                roughness: 0.8,
                side: THREE.DoubleSide
            });
            const cone = new THREE.Mesh(coneGeo, coneMat);
            cone.name = "cone";
            cone.position.y = -0.064;
            cone.castShadow = true;
            group.add(cone);
            
            // 3.5. Обод диффузора (rim) — полу-тор на внешнем краю конуса
            // Обеспечивает плавный закруглённый переход между конусом и подвеской,
            // устраняя острый угол при выдвижении диффузора наружу.
            // В сечении — полукольцо (половина тора): внутренний край (r=0.22) присоединён
            // к внешнему краю конуса, а верх (r=0.235, y=0.015) — к внутреннему краю подвески.
            // При движении диффузора перемещается жёстко вместе с ним (недеформируемый).
            const rimProfilePoints = [];
            const rimMainR = 0.235;
            const rimTubeR = 0.015;
            const rimProfileSegs = 12;
            for (let i = 0; i <= rimProfileSegs; i++) {
                const a = (Math.PI * i) / rimProfileSegs;
                rimProfilePoints.push(new THREE.Vector2(
                    rimMainR + rimTubeR * Math.cos(a),  // расстояние от оси Y
                    rimTubeR * Math.sin(a)                // высота полукольца
                ));
            }
            const rimGeo = new THREE.LatheGeometry(rimProfilePoints, 32);
            const rimMat = new THREE.MeshStandardMaterial({
                color: 0x111113,
                metalness: 0.1,
                roughness: 0.8,
                side: THREE.DoubleSide
            });
            const rim = new THREE.Mesh(rimGeo, rimMat);
            rim.name = "rim";
            rim.position.y = 0.002;  // На уровне внешнего края конуса (верх конуса y = 0.002)
            rim.castShadow = true;
            group.add(rim);
            
            // 4. Пылезащитный центральный колпачок (купол)
            // Широкий плоский купол (thetaLength=0.4π≈72°), увеличен до 0.093 для полного перекрытия без зазоров
            const capGeo = new THREE.SphereGeometry(0.093, 16, 16, 0, Math.PI * 2, 0, Math.PI * 0.4);
            const capMat = new THREE.MeshStandardMaterial({
                color: 0x18181b,
                metalness: 0.7,
                roughness: 0.25
            });
            const cap = new THREE.Mesh(capGeo, capMat);
            cap.name = "cap";
            cap.position.y = -0.145; // Утоплен к узкому срезу конуса, чуть глубже внутрь сферы
            cap.castShadow = true;
            group.add(cap);
            
            return group;
        }

        for (let i = 0; i < diffCount; i++) {
            if (i === 12) continue; // Динамик №13 удалён

            const offset = 2.0 / diffCount;
            const increment = Math.PI * (3.0 - Math.sqrt(5.0));
            const y = ((i * offset) - 1.0) + (offset / 2.0);
            const r = Math.sqrt(1.0 - y * y);
            const phi = ((i + 1) % diffCount) * increment;
            
            const normal = new THREE.Vector3(
                Math.cos(phi) * r,
                y,
                Math.sin(phi) * r
            ).normalize();

            // Точка установки на поверхности строения
            const pos = normal.clone().multiplyScalar(1.8);
            
            const diffGroup = createDiffuserMesh();
            // Углубляем динамик на 0.022 внутрь сферы, чтобы тор рамы выступал наполовину
            const insetPos = pos.clone().add(normal.clone().multiplyScalar(-0.022));
            diffGroup.position.copy(insetPos);
            
            // Направляем локальную ось Y диффузора наружу по нормали
            diffGroup.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), normal);
            
            // Записываем ID для отладки
            diffGroup.userData = { id: `Динамик #${i + 1}`, type: "speaker" };
            
            monolithGroup.add(diffGroup);
            
            diffusers.push({
                group: diffGroup,
                cone: diffGroup.getObjectByName("cone"),
                cap: diffGroup.getObjectByName("cap"),
                rim: diffGroup.getObjectByName("rim"),
                surround: diffGroup.getObjectByName("surround"),
                normal: normal,
                localNormal: new THREE.Vector3(0, 1, 0),
                basePos: insetPos.clone(),
                worldPos: new THREE.Vector3(),
                worldNormal: new THREE.Vector3(),
                displacement: 0.0,
                velocity: 0.0,
                index: i
            });
        }

        // --- СОЗДАНИЕ АНТРОПОГЕННЫХ ДЕТАЛЕЙ (ИСКЛЮЧАЯ НАЛОЖЕНИЯ С ДИНАМИКАМИ) ---
        const detailsGroup = new THREE.Group();
        monolithGroup.add(detailsGroup);

        // Вспомогательная проверка наложения объектов на динамики
        function isCollidingWithDiffusers(pos, minDist = 0.58) {
            for (let d = 0; d < diffusers.length; d++) {
                if (pos.distanceTo(diffusers[d].basePos) < minDist) {
                    return true;
                }
            }
            return false;
        }

        // Внешние технологические щиты/панели (как обшивка сооружения)
        const panelCount = 35;
        const panelGeo = new THREE.BoxGeometry(0.5, 0.5, 0.12);
        for (let i = 0; i < panelCount; i++) {
            let pos;
            let attempts = 0;
            // Пробуем сгенерировать позицию без наложений на динамики
            do {
                pos = getRandomSpherePos(1.8);
                attempts++;
            } while (isCollidingWithDiffusers(pos, 0.78) && attempts < 200);

            const pMesh = new THREE.Mesh(panelGeo, mainBodyMat);
            pMesh.position.copy(pos);
            pMesh.lookAt(0, 0, 0);
            pMesh.rotation.z += seededRandom() * Math.PI;
            pMesh.castShadow = true;
            pMesh.receiveShadow = true;
            pMesh.userData = { id: `Панель #${i + 1}`, type: "panel" };
            detailsGroup.add(pMesh);
        }

        // Сливные трубы и кабели, опоясывающие строение
        const pipeCount = 20;
        const pipeGeo = new THREE.CylinderGeometry(0.02, 0.02, 1.4, 8);
        const pipeMat = new THREE.MeshStandardMaterial({ color: 0x2e333d, roughness: 0.3, metalness: 0.9 });
        for (let i = 0; i < pipeCount; i++) {
            let pos;
            let attempts = 0;
            do {
                pos = getRandomSpherePos(1.8);
                attempts++;
            } while (isCollidingWithDiffusers(pos, 0.68) && attempts < 200);

            const pipe = new THREE.Mesh(pipeGeo, pipeMat);
            pipe.position.copy(pos);
            pipe.lookAt(0, 0, 0);
            pipe.rotation.x += Math.PI / 2;
            // Проверяем, не пересекает ли труба динамик #4 (индекс 3) и при необходимости поворачиваем на 90°
            const diff4Pos = diffusers.length > 3 ? diffusers[3].basePos : null;
            if (diff4Pos && pos.distanceTo(diff4Pos) < 0.85) {
                // Труба рядом с динамиком #4 — поворот на 90° вокруг нормали поверхности
                const surfaceNormal = pos.clone().normalize();
                const rotQuat = new THREE.Quaternion().setFromAxisAngle(surfaceNormal, Math.PI / 2);
                pipe.quaternion.premultiply(rotQuat);
                // Если после поворота пересечение сохраняется, переворачиваем на 180° в перпендикулярной плоскости
                // чтобы ось трубы не смотрела к центру сферы
                if (i === 18) {
                    const surfTangent = new THREE.Vector3(1, 0, 0).applyQuaternion(pipe.quaternion);
                    const extraRotQuat = new THREE.Quaternion().setFromAxisAngle(surfTangent, Math.PI / 2);
                    pipe.quaternion.premultiply(extraRotQuat);
                }
            }
            pipe.castShadow = true;
            pipe.receiveShadow = true;
            pipe.userData = { id: `Труба #${i + 1}`, type: "pipe" };
            detailsGroup.add(pipe);
        }

        // Светящиеся окна мегаструктуры (архитектурные огоньки)
        const windowCount = 80;
        const windowGeo = new THREE.BoxGeometry(0.035, 0.035, 0.015);
        const windowMat = new THREE.MeshBasicMaterial({ color: 0xffaa44 });
        const windows = [];
        for (let i = 0; i < windowCount; i++) {
            let pos;
            let attempts = 0;
            do {
                pos = getRandomSpherePos(1.83);
                attempts++;
            } while (isCollidingWithDiffusers(pos, 0.55) && attempts < 200);

            const win = new THREE.Mesh(windowGeo, windowMat);
            win.position.copy(pos);
            win.lookAt(0, 0, 0);
            win.userData = { id: `Окно #${i + 1}`, type: "window" };
            detailsGroup.add(win);
            windows.push(win);
        }

        // --- СИМУЛЯТОР ФИЗИКИ ПЫЛИНКОВ (ЧАСТИЦ) ---
        const particleCount = 1400;
        const particleGeo = new THREE.BufferGeometry();
        const pPositions = new Float32Array(particleCount * 3);
        const particles = [];

        // Распределение пылинок вокруг сооружения
        function getRandomVolumePos(minDist, maxDist) {
            const dir = new THREE.Vector3(
                Math.random() - 0.5,
                Math.random() - 0.5,
                Math.random() - 0.5
            ).normalize();
            const dist = minDist + Math.random() * (maxDist - minDist);
            return dir.multiplyScalar(dist);
        }

        for (let i = 0; i < particleCount; i++) {
            const pos = getRandomVolumePos(2.0, 7.5);
            pPositions[i * 3] = pos.x;
            pPositions[i * 3 + 1] = pos.y;
            pPositions[i * 3 + 2] = pos.z;

            particles.push({
                pos: pos.clone(),
                vel: new THREE.Vector3(0, 0, 0),
                rnd: Math.random()
            });
        }

        particleGeo.setAttribute('position', new THREE.BufferAttribute(pPositions, 3));

        // Текстура пылинки
        const pCanvas = document.createElement('canvas');
        pCanvas.width = 16;
        pCanvas.height = 16;
        const pCtx = pCanvas.getContext('2d');
        const pGrad = pCtx.createRadialGradient(8, 8, 0, 8, 8, 8);
        pGrad.addColorStop(0, 'rgba(255, 255, 255, 0.95)');
        pGrad.addColorStop(0.4, 'rgba(255, 255, 255, 0.45)');
        pGrad.addColorStop(1, 'rgba(255, 255, 255, 0)');
        pCtx.fillStyle = pGrad;
        pCtx.fillRect(0, 0, 16, 16);
        const pTexture = new THREE.CanvasTexture(pCanvas);

        const particleMat = new THREE.PointsMaterial({
            size: 0.065,
            map: pTexture,
            transparent: true,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
            color: 0xffebd4
        });

        const particleSystem = new THREE.Points(particleGeo, particleMat);
        scene.add(particleSystem);

        // --- Настройка Пост-процессинга ---
        const renderScene = new THREE.RenderPass(scene, camera);
        const bloomPass = new THREE.UnrealBloomPass(
            new THREE.Vector2(window.innerWidth, window.innerHeight),
            config.bloomIntensity,
            config.bloomRadius,
            0.65 // Высокий порог, чтобы светились только самые яркие технологичные окна и диффузоры
        );

        const fxaaPass = new THREE.ShaderPass(THREE.FXAAShader);
        const smaaPass = new THREE.SMAAPass(window.innerWidth, window.innerHeight);

        const composer = new THREE.EffectComposer(renderer);
        composer.addPass(renderScene);
        composer.addPass(bloomPass);
        composer.addPass(fxaaPass);
        composer.addPass(smaaPass);

        // Важно: SSAA 4× и 8× — это множитель количества сэмплов, а не линейный
        // множитель ширины/высоты. Поэтому реальный масштаб рендера = sqrt(samples).
        // Например, SSAA 4× = 2× по ширине и 2× по высоте, SSAA 8× = sqrt(8)×.
        let currentComposerPixelRatio = 1;

        function getScreenPixelRatio() {
            return Math.min(window.devicePixelRatio || 1, 2);
        }

        function getRequestedAAPixelRatio(mode) {
            const deviceRatio = getScreenPixelRatio();
            if (mode === "ssaa15") return deviceRatio * Math.sqrt(1.5);
            if (mode === "ssaa2") return deviceRatio * Math.sqrt(2.0);
            if (mode === "ssaa4") return deviceRatio * Math.sqrt(4.0);
            if (mode === "ssaa8") return deviceRatio * Math.sqrt(8.0);
            return deviceRatio;
        }

        function updateAAPassesResolution() {
            const renderW = Math.max(1, Math.floor(window.innerWidth * currentComposerPixelRatio));
            const renderH = Math.max(1, Math.floor(window.innerHeight * currentComposerPixelRatio));
            fxaaPass.material.uniforms['resolution'].value.set(1 / renderW, 1 / renderH);
            if (smaaPass.setSize) smaaPass.setSize(renderW, renderH);
        }

        function applyAntialiasingMode(mode) {
            config.antialiasing = mode;

            // renderer отвечает только за размер финального canvas. Supersampling делаем
            // через EffectComposer, чтобы не было двойного масштабирования и сдвига/зума сцены.
            renderer.setPixelRatio(getScreenPixelRatio());
            renderer.setSize(window.innerWidth, window.innerHeight);

            currentComposerPixelRatio = getRequestedAAPixelRatio(mode);
            if (composer.setPixelRatio) composer.setPixelRatio(currentComposerPixelRatio);
            composer.setSize(window.innerWidth, window.innerHeight);

            fxaaPass.enabled = (mode === "fxaa");
            smaaPass.enabled = (mode === "smaa");
            updateAAPassesResolution();
        }

        applyAntialiasingMode(config.antialiasing);

        // --- Элементы Управления Темами ---
        function applyPalette(key) {
            const pal = PALETTES[key];
            if (!pal) return;

            // Фон и задымление шейдера
            const baseBg = new THREE.Color(pal.bg);
            const colorCenter = baseBg.clone().multiplyScalar(1.4); // делаем центр чуть светлее
            const colorEdge = baseBg.clone().multiplyScalar(0.6);   // делаем края темнее
            bgShaderMaterial.uniforms.color1.value.copy(colorCenter);
            bgShaderMaterial.uniforms.color2.value.copy(colorEdge);

            // Цвета интерфейса
            document.documentElement.style.setProperty('--accent', pal.accent);
            document.documentElement.style.setProperty('--accent-glow', pal.accentGlow);

            // Основное здание и панели
            if (mainBodyMat) {
                mainBodyMat.color.setHex(pal.monolithColor);
                mainBodyMat.roughness = pal.monolithRoughness;
                mainBodyMat.metalness = pal.monolithMetalness;
            }

            // Диффузоры (рама)
            diffusers.forEach(diff => {
                const frame = diff.group.children[0];
                if (frame && frame.material) {
                    frame.material.color.setHex(pal.frameColor);
                }
            });

            // Технологические огоньки
            windowMat.color.setHex(pal.windowGlow);

            // Окрас пылинок
            particleMat.color.setHex(pal.dustColor);
        }

        applyPalette(config.activeTheme);

        // --- WebSocket соединение ---
        function connectWebSocket() {
            const ws = new WebSocket('ws://localhost:8765');
            ws.onopen = () => {
                console.log("WebSocket подключен к серверу анализа аудио.");
            };
            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    rawData.bass = data.bass || 0.0;
                    rawData.mid = data.mid || 0.0;
                    rawData.treble = data.treble || 0.0;
                    rawData.spectrum = data.spectrum || Array(64).fill(0);
                    rawData.device_name = data.device_name || t('deviceWaiting');
                } catch (e) {
                    console.error("Ошибка десериализации аудиоданных:", e);
                }
            };
            ws.onclose = () => {
                rawData.device_name = t('deviceConnecting');
                setTimeout(connectWebSocket, 2000);
            };
            ws.onerror = () => ws.close();
        }
        connectWebSocket();

        // --- UI Логика Авто-Скрытия ---
        const controlPanel = document.getElementById('control-panel');
        const statsOverlay = document.getElementById('stats-overlay');
        const instructionTooltip = document.getElementById('instruction-tooltip');
        const deviceNameEl = document.getElementById('device-name');

        const meterBass = document.getElementById('meter-bass');
        const meterMid = document.getElementById('meter-mid');
        const meterTreble = document.getElementById('meter-treble');

        let uiTimer;
        let isMouseOverPanel = false;

        function showUI() {
            controlPanel.classList.add('visible');
            statsOverlay.classList.add('visible');
            instructionTooltip.classList.add('visible');
            document.body.style.cursor = 'default';

            clearTimeout(uiTimer);
            uiTimer = setTimeout(() => {
                if (!isMouseOverPanel) {
                    hideUI();
                }
            }, 3000); // 3 секунды без движения
        }

        function hideUI() {
            controlPanel.classList.remove('visible');
            statsOverlay.classList.remove('visible');
            instructionTooltip.classList.remove('visible');
            document.body.style.cursor = 'none'; // Полный кинематографичный режим
        }

        // --- РЕЙКАСТИНГ ДЛЯ ОТОБРАЖЕНИЯ ОТЛАДОЧНЫХ НОМЕРОВ ПРИ НАВЕДЕНИИ ---
        // По умолчанию полностью отключен через config.debugObjectLabels = false.
        // В отключенном состоянии не создается Raycaster, не подписывается mousemove-обработчик
        // и не выполняются intersectObjects/project — то есть лишние расчеты для плашек отсутствуют.
        const debugLabelEl = document.getElementById('debug-label');

        if (config.debugObjectLabels) {
            const raycaster = new THREE.Raycaster();
            const mouse2D = new THREE.Vector2();
            const debugWorldPos = new THREE.Vector3();

            document.addEventListener('mousemove', (event) => {
                // Преобразуем координаты мыши в нормализованные (-1 до 1)
                mouse2D.x = (event.clientX / window.innerWidth) * 2 - 1;
                mouse2D.y = -(event.clientY / window.innerHeight) * 2 + 1;

                // Обновляем луч от камеры
                raycaster.setFromCamera(mouse2D, camera);

                // Проверяем пересечения со всеми деталями мегаструктуры и колонками
                const intersects = raycaster.intersectObjects(monolithGroup.children, true);

                if (intersects.length > 0) {
                    // Ищем объект с сохраненным ID, двигаясь вверх по дереву родителей
                    let targetObj = intersects[0].object;
                    let objName = "";
                    while (targetObj && targetObj !== scene) {
                        if (targetObj.userData && targetObj.userData.id) {
                            objName = targetObj.userData.id;
                            break;
                        }
                        targetObj = targetObj.parent;
                    }

                    if (objName) {
                        // Переводим 3D-координаты объекта в 2D-координаты экрана
                        intersects[0].object.getWorldPosition(debugWorldPos);
                        debugWorldPos.project(camera);

                        // Рассчитываем позицию на экране
                        const x = (debugWorldPos.x * 0.5 + 0.5) * window.innerWidth;
                        const y = (-(debugWorldPos.y * 0.5) + 0.5) * window.innerHeight;

                        // Отображаем подсказку с отступом справа
                        debugLabelEl.style.display = 'block';
                        debugLabelEl.style.left = `${x + 22}px`;
                        debugLabelEl.style.top = `${y - 12}px`;
                        debugLabelEl.innerHTML = `⚙️ ${objName}`;
                    } else {
                        debugLabelEl.style.display = 'none';
                    }
                } else {
                    debugLabelEl.style.display = 'none';
                }
            });
        } else {
            debugLabelEl.style.display = 'none';
        }

        controlPanel.addEventListener('mouseenter', () => { isMouseOverPanel = true; showUI(); });
        controlPanel.addEventListener('mouseleave', () => { isMouseOverPanel = false; showUI(); });
        document.addEventListener('mousemove', showUI);
        document.addEventListener('keydown', showUI);

        // Связывание слайдеров с физическим ядром
        const sliders = [
            { id: "slide-gravity", prop: "gravityStrength", valId: "val-gravity" },
            { id: "slide-viscosity", prop: "viscosity", valId: "val-viscosity" },
            { id: "slide-turbulence", prop: "turbulence", valId: "val-turbulence" },
            { id: "slide-repulsion", prop: "repulsionForce", valId: "val-repulsion" },
            { id: "slide-sens", prop: "sensToBoom", valId: "val-sens" },
            { id: "slide-spring", prop: "springConstant", valId: "val-spring" },
            { id: "slide-vibr", prop: "vibrationAmp", valId: "val-vibr" },
            { id: "slide-bloom", prop: "bloomIntensity", valId: "val-bloom" },
            { id: "slide-radius", prop: "bloomRadius", valId: "val-radius" },
            { id: "slide-shake", prop: "screenShake", valId: "val-shake" },
            { id: "slide-cam-rot", prop: "cameraRotationSpeed", valId: "val-cam-rot" },
        ];

        sliders.forEach(s => {
            const sliderEl = document.getElementById(s.id);
            const valEl = document.getElementById(s.valId);
            if (sliderEl && valEl) {
                sliderEl.addEventListener('input', (e) => {
                    const val = parseFloat(e.target.value);
                    config[s.prop] = val;
                    valEl.textContent = val.toFixed(s.prop === "springConstant" ? 1 : 2);
                    
                    if (s.prop === "bloomIntensity") bloomPass.strength = val;
                    if (s.prop === "bloomRadius") bloomPass.radius = val;
                });
            }
        });

        document.getElementById('select-theme').addEventListener('change', (e) => {
            config.activeTheme = e.target.value;
            applyPalette(config.activeTheme);
        });

        document.getElementById('select-antialiasing').addEventListener('change', (e) => {
            applyAntialiasingMode(e.target.value);
        });

        document.getElementById('select-trajectory').addEventListener('change', (e) => {
            config.rotationTrajectory = e.target.value;
        });

        document.getElementById('select-language').addEventListener('change', (e) => {
            applyLocalization(e.target.value);
        });

        // Запуск интерфейса
        applyLocalization('en');
        showUI();

        // --- Переменная режима энергосбережения ---
        let isRenderActive = true;

        document.getElementById('toggle-render-mode').addEventListener('change', (e) => {
            isRenderActive = e.target.checked;
        });

        // --- Главный Физический Цикл Рендеринга ---
        let lastTime = 0;
        let time = 0;
        let prevRawBass = 0;
        const shakeOffset = new THREE.Vector3();

        function animate(timestamp) {
            requestAnimationFrame(animate);

            // Если включен режим энергосбережения, пропускаем все расчеты и рендеринг для экономии 100% GPU
            if (!isRenderActive) {
                return;
            }

            const delta = lastTime ? Math.min((timestamp - lastTime) / 1000, 0.05) : 0.016;
            lastTime = timestamp;
            time += delta;

            // Обновляем время в шейдере заднего фона
            bgShaderMaterial.uniforms.time.value = time;

            // Интерполяция данных аудио
            const ease = 0.15;
            smoothData.bass += (rawData.bass * config.sensToBoom - smoothData.bass) * ease;
            smoothData.mid += (rawData.mid - smoothData.mid) * ease;
            smoothData.treble += (rawData.treble - smoothData.treble) * ease;
            
            for (let i = 0; i < 64; i++) {
                const targetVal = rawData.spectrum[i] || 0.0;
                smoothData.spectrum[i] += (targetVal - smoothData.spectrum[i]) * ease;
            }

            // Обновление диагностического 2D UI
            deviceNameEl.textContent = localizeDeviceName(rawData.device_name);

            // "Honest" UI calibration: Calculate UI-only values from the spectrum 
            // without extra multipliers (coefficients).
            const getAvg = (arr) => arr.length > 0 ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;
            
            // We use the raw average energy in each band.
            const uiBassTarget = getAvg(rawData.spectrum.slice(0, 6));
            const uiMidTarget = getAvg(rawData.spectrum.slice(6, 26));
            const uiTrebleTarget = getAvg(rawData.spectrum.slice(26, 64)); // All remaining high bands

            // Professional meter logic: fast rise (attack) and natural fall (decay).
            // This prevents the bars from jumping too erratically while remaining "honest".
            const riseSpeed = 0.35; 
            const fallSpeed = 0.07; 

            const updateBar = (current, target) => {
                const delta = target - current;
                return current + delta * (delta > 0 ? riseSpeed : fallSpeed);
            };

            uiSmooth.bass = updateBar(uiSmooth.bass, uiBassTarget);
            uiSmooth.mid = updateBar(uiSmooth.mid, uiMidTarget);
            uiSmooth.treble = updateBar(uiSmooth.treble, uiTrebleTarget);

            meterBass.style.width = `${Math.min(uiSmooth.bass * 100, 100)}%`;
            meterMid.style.width = `${Math.min(uiSmooth.mid * 100, 100)}%`;
            meterTreble.style.width = `${Math.min(uiSmooth.treble * 100, 100)}%`;

            // Обнаружение басовых ударов "Бум"
            const bassDiff = rawData.bass - prevRawBass;
            prevRawBass = rawData.bass;
            const isBoom = (bassDiff > 0.18 && rawData.bass > 0.5) || (rawData.bass > 0.85 && Math.random() < 0.05);

            // --- 1. ФИЗИКА ДИФФУЗОРОВ ---
            // Считываем их мировые координаты с учетом вращения всей мегаструктуры
            diffusers.forEach(diff => {
                diff.group.getWorldPosition(diff.worldPos);
                // Направление нормали диффузора в мировом пространстве
                const q = new THREE.Quaternion();
                diff.group.getWorldQuaternion(q);
                diff.worldNormal.copy(diff.localNormal).applyQuaternion(q).normalize();

                // Поведение при мощном ударе ("бум")
                if (isBoom) {
                    // Диффузор взрывно выдвигается вперед наружу (ограниченная реалистичная сила)
                    diff.velocity = config.repulsionForce * (0.45 + Math.random() * 0.25);
                }

                // Обычное покачивание/вибрация в такт СЧ и ВЧ частот
                const normalVibration = Math.sin(time * 65.0 + diff.index) * config.vibrationAmp * smoothData.mid;

                // Математическая модель упругого пружинного резонатора (Spring Physics)
                const springForce = -config.springConstant * diff.displacement;
                const dampingForce = -config.springDamping * diff.velocity;
                const accel = springForce + dampingForce;

                diff.velocity += accel * delta;
                diff.displacement += diff.velocity * delta;

                // Жесткое ограничение максимального хода мембраны (Speaker Excursion Limits Xmax)
                // Это предотвращает появление щелей и зазоров между рамой и конусом
                const maxExcursionOut = 0.045;
                const maxExcursionIn = -0.025;
                diff.displacement = Math.max(maxExcursionIn, Math.min(diff.displacement, maxExcursionOut));

                // Финальное смещение с учетом вибрации
                const finalY = diff.displacement + normalVibration;
                
                // Перемещаем конус, обод (rim) и пылезащитный колпачок
                diff.cone.position.y = -0.064 + finalY;
                if (diff.rim) diff.rim.position.y = 0.002 + finalY;
                diff.cap.position.y = -0.145 + finalY;

                // Обновляем геометрию подвеса: внешний край неподвижен (рама),
                // внутренний следует за диффузором, полу-ролик адаптируется к смещению
                if (diff.surround) {
                    updateSurroundVertices(diff.surround.geometry, finalY);
                }
            });

            // --- 2. ФИЗИКА ПЫЛИНОК (ГРАВИТАЦИЯ + ВОЗДУШНЫЙ ВЗРЫВ) ---
            const pArray = particleGeo.attributes.position.array;
            const tempDiffToPart = new THREE.Vector3();

            for (let i = 0; i < particleCount; i++) {
                const p = particles[i];

                // А. Сила Гравитации к центру монолита (F_g = g / dist^2)
                const toCenter = new THREE.Vector3(0, 0, 0).sub(p.pos);
                const distToCenter = toCenter.length();
                if (distToCenter > 0.1) {
                    toCenter.normalize();
                    const gravityForce = config.gravityStrength / (distToCenter * distToCenter + 0.3);
                    p.vel.addScaledVector(toCenter, gravityForce * delta);
                }

                // Б. Воздушные удары от движущихся наружу диффузоров
                diffusers.forEach(diff => {
                    // Только когда диффузор резко толкает воздух вперед (скорость движения > 0)
                    if (diff.velocity > 0.1) {
                        tempDiffToPart.copy(p.pos).sub(diff.worldPos);
                        const distToDiff = tempDiffToPart.length();

                        if (distToDiff < config.blastRadius) {
                            tempDiffToPart.normalize();
                            // Физическое падение давления/силы ветра по закону обратных квадратов
                            const windForce = (diff.velocity * config.repulsionForce * 1.5) / (distToDiff * distToDiff + 0.5);

                            // Вектор выталкивания воздуха: смесь направления диффузора и радиального вектора
                            const pushDir = tempDiffToPart.clone().lerp(diff.worldNormal, 0.45).normalize();
                            p.vel.addScaledVector(pushDir, windForce * delta);
                        }
                    }
                });

                // В. Сопротивление/Вязкость среды (эффект медленного оседания в желе)
                p.vel.multiplyScalar(1.0 - config.viscosity * delta);

                // Г. Естественные случайные завихрения воздушных потоков (Броуновский дрейф)
                if (config.turbulence > 0) {
                    p.vel.x += Math.sin(p.pos.y * 2.5 + time) * config.turbulence * 0.15 * delta;
                    p.vel.y += Math.cos(p.pos.z * 2.5 + time) * config.turbulence * 0.15 * delta;
                    p.vel.z += Math.sin(p.pos.x * 2.5 + time) * config.turbulence * 0.15 * delta;
                }

                // Д. Интегрируем скорость в координату перемещения
                p.pos.addScaledVector(p.vel, delta);

                // Е. Коллизии со сферой и внешними границами (Мягкий респаун)
                const finalDist = p.pos.length();
                if (finalDist < 1.85) {
                    // Пылинка коснулась поверхности мегаструктуры - оседает и плавно респаунится в облаке снаружи
                    p.pos.copy(getRandomVolumePos(5.0, 7.5));
                    p.vel.set(0, 0, 0);
                } else if (finalDist > 8.0) {
                    // Пылинку унесло слишком далеко воздушным потоком - возвращаем обратно в атмосферу
                    p.pos.copy(getRandomVolumePos(3.0, 5.5));
                    p.vel.set(0, 0, 0);
                }

                // Запись новых координат в буфер геометрии
                pArray[i * 3] = p.pos.x;
                pArray[i * 3 + 1] = p.pos.y;
                pArray[i * 3 + 2] = p.pos.z;
            }
            particleGeo.attributes.position.needsUpdate = true;

            // --- 3. ВРАЩЕНИЕ МЕГАСТРУКТУРЫ И АНИМАЦИЯ КАМЕРЫ ---
            if (config.cameraRotationSpeed > 0) {
                // Медленно вращаем всё сооружение со всеми его придатками.
                // Траектория выбирается в нижней строке UI: nonCyclic — новый неповторяющийся дрейф,
                // classic — прежняя точная траектория 0.15 по Y и 0.05 по X.
                const rotPath = ROTATION_TRAJECTORIES[config.rotationTrajectory] || ROTATION_TRAJECTORIES.nonCyclic;
                monolithGroup.rotation.y += config.cameraRotationSpeed * rotPath.y * delta;
                monolithGroup.rotation.x += config.cameraRotationSpeed * rotPath.x * delta;
            }

            // Накапливаем медленное мерцание окон сооружения в такт музыки
            windows.forEach((win, index) => {
                const specIndex = index % 32;
                const activity = smoothData.spectrum[specIndex] || 0.0;
                win.scale.setScalar(1.0 + activity * 1.5);
            });

            // --- 4. ДРОЖАНИЕ КАМЕРЫ И СВЕЧЕНИЕ НА УДАРАХ ---
            if (isBoom && config.screenShake > 0) {
                // Разовая сильная встряска при детонации басового диффузора
                const power = config.screenShake * 0.12;
                shakeOffset.set(
                    (Math.random() - 0.5) * power,
                    (Math.random() - 0.5) * power,
                    (Math.random() - 0.5) * power
                );
                camera.position.add(shakeOffset);
            } else {
                shakeOffset.set(0, 0, 0);
            }

            // Динамический скачок Bloom-эффекта на басах
            bloomPass.strength = config.bloomIntensity + Math.max(0, smoothData.bass - 0.2) * 1.2;

            controls.update();
            composer.render();

            // Сброс вибрации камеры для стабильности OrbitControls
            if (shakeOffset.lengthSq() > 0) {
                camera.position.sub(shakeOffset);
            }
        }

        // --- Обработка Изменения Размеров Экран ---
        window.addEventListener('resize', () => {
            const w = window.innerWidth;
            const h = window.innerHeight;

            camera.aspect = w / h;
            camera.updateProjectionMatrix();

            applyAntialiasingMode(config.antialiasing);
        });

        animate(0);
    </script>
</body>
</html>
"""

# --- PYTHON ПОТОК ЗАХВАТА ЗВУКА И БЫСТРОГО ПРЕОБРАЗОВАНИЯ ФУРЬЕ (FFT) ---
def audio_capture_loop():
    global latest_fft_data
    import pyaudiowpatch as pyaudio
    
    p = pyaudio.PyAudio()
    try:
        wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    except OSError:
        print("[ОШИБКА] Драйвер WASAPI не поддерживается или отключен в Windows.")
        return

    default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
    if not default_speakers["isLoopbackDevice"]:
        for loopback in p.get_loopback_device_info_generator():
            if default_speakers["name"] in loopback["name"]:
                default_speakers = loopback
                break
        else:
            print("[ОШИБКА] Локальный петлевой аудиовыход (Loopback) не обнаружен.")
            return

    device_name = default_speakers["name"]
    channels = default_speakers["maxInputChannels"]
    rate = int(default_speakers["defaultSampleRate"])
    
    print(f"-> Перехват системного аудио запущен: [{device_name}]")
    
    stream = p.open(
        format=pyaudio.paInt16,
        channels=channels,
        rate=rate,
        input=True,
        input_device_index=default_speakers["index"],
        frames_per_buffer=CHUNK_SIZE
    )
    
    hanning_window = np.hanning(CHUNK_SIZE)
    
    while True:
        try:
            raw_bytes = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            audio_data = np.frombuffer(raw_bytes, dtype=np.int16)
            
            if len(audio_data) < CHUNK_SIZE:
                continue
                
            if channels > 1:
                audio_data = audio_data.reshape(-1, channels)
                audio_data = audio_data.mean(axis=1)
                
            windowed_data = audio_data * hanning_window
            fft_complex = np.fft.rfft(windowed_data)
            fft_mag = np.abs(fft_complex)
            fft_norm = fft_mag / (32768.0 * (CHUNK_SIZE / 2))
            
            bins_count = 64
            chunk_step = max(1, len(fft_norm) // bins_count)
            spectrum = []
            
            for i in range(bins_count):
                bin_slice = fft_norm[i * chunk_step : (i + 1) * chunk_step]
                val = np.mean(bin_slice) if len(bin_slice) > 0 else 0.0
                spectrum.append(float(np.clip(val * 2400.0, 0.0, 1.0)))
                
            bass_val = np.mean(spectrum[0:6]) if len(spectrum) >= 6 else 0.0
            mid_val = np.mean(spectrum[6:26]) if len(spectrum) >= 26 else 0.0
            treble_val = np.mean(spectrum[26:55]) if len(spectrum) >= 55 else 0.0
            
            with data_lock:
                latest_fft_data = {
                    "device_name": device_name,
                    "bass": float(np.clip(bass_val * 1.6, 0.0, 1.0)),
                    "mid": float(np.clip(mid_val * 1.3, 0.0, 1.0)),
                    "treble": float(np.clip(treble_val * 1.2, 0.0, 1.0)),
                    "spectrum": spectrum
                }
                
        except Exception as e:
            print(f"[ПРЕДУПРЕЖДЕНИЕ] Сбой захвата кадра аудио: {e}")
            break
            
    stream.stop_stream()
    stream.close()
    p.terminate()

# --- PYTHON WEBSOCKET СЕРВЕР ДЛЯ ПЕРЕДАЧИ ДАННЫХ В БРАУЗЕР ---
async def ws_handler(websocket):
    print("-> Браузер успешно подключился к WebSockets.")
    try:
        while True:
            with data_lock:
                data_str = json.dumps(latest_fft_data)
            await websocket.send(data_str)
            await asyncio.sleep(1 / 60)
    except websockets.exceptions.ConnectionClosed:
        print("-> Наблюдается отключение браузера от WebSockets.")

async def start_ws_server():
    async with websockets.serve(ws_handler, "127.0.0.1", WS_PORT):
        await asyncio.Event().wait()

# --- ВСТРОЕННЫЙ МИНИ-ВЕБ-СЕРВЕР ДЛЯ ХОСТИНГА СТРАНИЦЫ ---
class EmbeddedHTMLHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode("utf-8"))
        else:
            self.send_error(404, "File not found")

    def log_message(self, format, *args):
        pass

def run_http_server():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", HTTP_PORT), EmbeddedHTMLHandler) as httpd:
        print(f"-> Веб-визуализатор запущен: [http://localhost:{HTTP_PORT}]")
        httpd.serve_forever()

# --- АВТОМАТИЧЕСКОЕ ОТКРЫТИЕ СТРАНИЦЫ В БРАУЗЕРЕ ---
def auto_open_browser():
    time.sleep(1.5)  # Небольшая пауза, чтобы сервер успел запуститься
    import webbrowser
    url = f"http://localhost:{HTTP_PORT}"
    print(f"-> Автоматическое открытие визуализатора в браузере: {url}")
    webbrowser.open(url)

# --- СТАРТ СИСТЕМЫ ---
if __name__ == "__main__":
    print("==========================================================")
    print("       MONOLITH REACTOR ACTIVE (High-Fidelity 3D Physics) ")
    print("==========================================================")
    
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    
    capture_thread = threading.Thread(target=audio_capture_loop, daemon=True)
    capture_thread.start()
    
    # Запуск потока автоматического открытия браузера
    browser_thread = threading.Thread(target=auto_open_browser, daemon=True)
    browser_thread.start()
    
    print(f"-> WebSocket-сервер ожидает соединений на порту {WS_PORT}")
    try:
        asyncio.run(start_ws_server())
    except KeyboardInterrupt:
        print("\nЗавершение работы серверов...")
