#!/usr/bin/env python3
"""
Script de monitoring Freebox
Récupère les données via l'API Freebox et les expose via une API REST
"""

import hashlib
import hmac
import json
import time
import requests
from flask import Flask, jsonify, render_template_string
from flask_cors import CORS
import os
import sqlite3
import threading
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

# Configuration
FREEBOX_URL = "http://mafreebox.freebox.fr"
APP_ID = "fr.freebox.monitor"
APP_NAME = "Freebox Monitor"
APP_VERSION = "1.0.0"
DEVICE_NAME = "Server"

# Fichier pour stocker le token (dans /app/data pour persistance Docker)
TOKEN_FILE = "/app/data/freebox_token.json" if os.path.exists("/app/data") else "freebox_token.json"

# Configuration de la base de données
DB_PATH = '/app/data/freebox_history.db' if os.path.exists("/app/data") else 'freebox_history.db'

def init_database():
    """Initialise la base de données SQLite pour l'historique"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bandwidth_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            download_rate REAL NOT NULL,
            upload_rate REAL NOT NULL,
            temperature REAL
        )
    ''')
    
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON bandwidth_history(timestamp)')
    
    conn.commit()
    conn.close()
    print("✓ Base de données initialisée")

def save_stats(download_rate, upload_rate, temperature):
    """Sauvegarde les statistiques dans la base de données"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        
        timestamp = int(time.time())
        cursor.execute(
            'INSERT INTO bandwidth_history (timestamp, download_rate, upload_rate, temperature) VALUES (?, ?, ?, ?)',
            (timestamp, download_rate, upload_rate, temperature)
        )
        
        conn.commit()
        conn.close()
    except sqlite3.OperationalError as e:
        print(f"✗ Erreur SQLite (opération): {e}")
    except Exception as e:
        print(f"✗ Erreur sauvegarde stats: {type(e).__name__} - {e}")

def cleanup_old_data():
    """Nettoie les données de plus de 30 jours"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        thirty_days_ago = int(time.time()) - (30 * 24 * 3600)
        cursor.execute('DELETE FROM bandwidth_history WHERE timestamp < ?', (thirty_days_ago,))
        deleted = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        if deleted > 0:
            print(f"✓ Nettoyage: {deleted} entrées supprimées")
    except Exception as e:
        print(f"✗ Erreur nettoyage: {e}")

# HTML de l'interface intégré
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Monitoring Freebox</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #282a36 0%, #1a1b26 100%);
            color: #f8f8f2;
            min-height: 100vh;
            padding: 20px;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
        }

        .header {
            background: rgba(68, 71, 90, 0.3);
            border: 1px solid #6272a4;
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 30px;
            backdrop-filter: blur(10px);
        }

        .header h1 {
            color: #bd93f9;
            font-size: 2em;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 15px;
        }

        .header h1::before {
            content: "📊";
            font-size: 1.2em;
        }

        .status-badge {
            display: inline-block;
            padding: 8px 16px;
            background: #50fa7b;
            color: #282a36;
            border-radius: 20px;
            font-weight: bold;
            font-size: 0.9em;
            margin-left: 20px;
        }

        .status-badge.offline {
            background: #ff5555;
            color: #f8f8f2;
        }

        .status-badge.connecting {
            background: #f1fa8c;
            color: #282a36;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .card {
            background: rgba(68, 71, 90, 0.3);
            border: 1px solid #6272a4;
            border-radius: 12px;
            padding: 20px;
            backdrop-filter: blur(10px);
            transition: all 0.3s ease;
        }

        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(189, 147, 249, 0.2);
            border-color: #bd93f9;
        }

        .card-title {
            color: #8be9fd;
            font-size: 1.2em;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .card-value {
            font-size: 2em;
            color: #50fa7b;
            font-weight: bold;
            margin: 10px 0;
        }

        .card-label {
            color: #f8f8f2;
            font-size: 0.9em;
            opacity: 0.8;
        }

        .progress-bar {
            width: 100%;
            height: 20px;
            background: rgba(98, 114, 164, 0.3);
            border-radius: 10px;
            overflow: hidden;
            margin: 10px 0;
        }

        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #50fa7b, #8be9fd);
            border-radius: 10px;
            transition: width 0.5s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #282a36;
            font-weight: bold;
            font-size: 0.8em;
        }

        .progress-fill.warning {
            background: linear-gradient(90deg, #f1fa8c, #ffb86c);
        }

        .progress-fill.danger {
            background: linear-gradient(90deg, #ff5555, #ff79c6);
        }

        .info-row {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid rgba(98, 114, 164, 0.3);
        }

        .info-row:last-child {
            border-bottom: none;
        }

        .info-label {
            color: #f8f8f2;
            opacity: 0.8;
        }

        .info-value {
            color: #bd93f9;
            font-weight: bold;
        }

        .refresh-btn {
            background: linear-gradient(135deg, #bd93f9, #ff79c6);
            color: #f8f8f2;
            border: none;
            padding: 12px 30px;
            border-radius: 8px;
            font-size: 1em;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s ease;
            margin-top: 20px;
        }

        .refresh-btn:hover {
            transform: scale(1.05);
            box-shadow: 0 5px 20px rgba(189, 147, 249, 0.4);
        }

        .refresh-btn:active {
            transform: scale(0.98);
        }

        .refresh-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .last-update {
            text-align: center;
            color: #6272a4;
            margin-top: 10px;
            font-size: 0.9em;
        }

        .connection-info {
            grid-column: 1 / -1;
        }

        .error-message {
            background: rgba(255, 85, 85, 0.2);
            border: 1px solid #ff5555;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 20px;
            color: #ff5555;
            display: none;
        }

        .error-message.show {
            display: block;
        }

        @keyframes pulse {
            0%, 100% {
                opacity: 1;
            }
            50% {
                opacity: 0.5;
            }
        }

        .loading {
            animation: pulse 2s infinite;
        }
        
        /* Styles pour les onglets */
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            border-bottom: 2px solid rgba(98, 114, 164, 0.3);
            padding-bottom: 10px;
        }
        
        .tab {
            padding: 10px 20px;
            background: rgba(68, 71, 90, 0.5);
            border: none;
            color: #f8f8f2;
            cursor: pointer;
            border-radius: 8px 8px 0 0;
            font-size: 0.9em;
            transition: all 0.3s ease;
        }
        
        .tab:hover {
            background: rgba(98, 114, 164, 0.5);
        }
        
        .tab.active {
            background: #6272a4;
            color: #282a36;
            font-weight: bold;
        }
        
        .tab-content {
            display: none;
        }
        
        .tab-content.active {
            display: block;
        }
        
        .history-chart {
            width: 100%;
            height: 300px;
            background: rgba(40, 42, 54, 0.5);
            border-radius: 8px;
            margin: 20px 0;
        }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>
                Monitoring Freebox
                <span class="status-badge" id="statusBadge">Connexion...</span>
            </h1>
            <p style="color: #6272a4; margin-top: 10px;">Supervision en temps réel</p>
        </div>

        <div class="error-message" id="errorMessage">
            <strong>⚠️ Erreur:</strong> <span id="errorText"></span>
        </div>

        <!-- Onglets de navigation -->
        <div class="tabs">
            <button class="tab active" onclick="switchTab('realtime')">⚡ Temps réel</button>
            <button class="tab" onclick="switchTab('24h')">📊 24 heures</button>
            <button class="tab" onclick="switchTab('7d')">📈 7 jours</button>
            <button class="tab" onclick="switchTab('30d')">📉 30 jours</button>
        </div>

        <!-- Contenu Temps Réel -->
        <div id="tab-realtime" class="tab-content active">
        <div class="grid">
            <!-- Débit descendant -->
            <div class="card">
                <div class="card-title">⬇️ Débit Descendant</div>
                <div class="card-value" id="downloadSpeed">-- Mb/s</div>
                <canvas id="downloadChart" style="max-height: 150px; margin-top: 10px;"></canvas>
                <div class="card-label" style="margin-top: 10px;">Capacité max: <span id="maxDownload">-- Mb/s</span></div>
            </div>

            <!-- Débit montant -->
            <div class="card">
                <div class="card-title">⬆️ Débit Montant</div>
                <div class="card-value" id="uploadSpeed">-- Mb/s</div>
                <canvas id="uploadChart" style="max-height: 150px; margin-top: 10px;"></canvas>
                <div class="card-label" style="margin-top: 10px;">Capacité max: <span id="maxUpload">-- Mb/s</span></div>
            </div>

            <!-- Température -->
            <div class="card">
                <div class="card-title">🌡️ Température</div>
                <div class="card-value" id="temperature">-- °C</div>
                <div class="progress-bar">
                    <div class="progress-fill" id="tempProgress" style="width: 0%">0%</div>
                </div>
                <div class="card-label">Température CPU / Switch</div>
            </div>

            <!-- Uptime -->
            <div class="card">
                <div class="card-title">⏱️ Uptime</div>
                <div class="card-value" id="uptime" style="font-size: 1.5em;">-- j --h --m</div>
                <div class="card-label">Temps depuis le dernier redémarrage</div>
            </div>
        </div>

        <!-- Informations de connexion -->
        <div class="card connection-info">
            <div class="card-title">🌐 Informations de Connexion</div>
            <div class="info-row">
                <span class="info-label">Adresse IPv4 publique</span>
                <span class="info-value" id="publicIP">--</span>
            </div>
            <div class="info-row">
                <span class="info-label">Adresse IPv6</span>
                <span class="info-value" id="publicIPv6">--</span>
            </div>
            <div class="info-row">
                <span class="info-label">État de la ligne</span>
                <span class="info-value" id="lineState">--</span>
            </div>
            <div class="info-row">
                <span class="info-label">Type de connexion</span>
                <span class="info-value" id="connectionType">--</span>
            </div>
            <div class="info-row">
                <span class="info-label">Media</span>
                <span class="info-value" id="connectionMedia">--</span>
            </div>
            <div class="info-row">
                <span class="info-label">Bande passante</span>
                <span class="info-value" id="bandwidth">⬇️ -- / ⬆️ -- Mb/s</span>
            </div>
        </div>

        <!-- Informations système -->
        <div class="grid">
            <div class="card">
                <div class="card-title">💾 Informations Système</div>
                <div class="info-row">
                    <span class="info-label">Modèle</span>
                    <span class="info-value" id="boardName">--</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Numéro de série</span>
                    <span class="info-value" id="serial">--</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Firmware</span>
                    <span class="info-value" id="firmware">--</span>
                </div>
            </div>

            <div class="card">
                <div class="card-title">🔌 Réseau Local</div>
                <div class="card-value" id="connectedDevices">--</div>
                <div class="card-label">Appareils actifs / Total: <span id="totalDevices">--</span></div>
            </div>

            <div class="card">
                <div class="card-title">📊 Données transférées</div>
                <div class="info-row">
                    <span class="info-label">Reçues</span>
                    <span class="info-value" id="rxBytes">-- GB</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Envoyées</span>
                    <span class="info-value" id="txBytes">-- GB</span>
                </div>
            </div>
        </div>

        <!-- Informations WiFi -->
        <div class="card connection-info">
            <div class="card-title">📡 Informations WiFi</div>
            <div class="info-row">
                <span class="info-label">État WiFi</span>
                <span class="info-value" id="wifiEnabled">--</span>
            </div>
            <div id="wifiAPDetails"></div>
        </div>

        <div style="text-align: center;">
            <button class="refresh-btn" id="refreshBtn" onclick="refreshData()">🔄 Actualiser les données</button>
            <div class="last-update">Dernière mise à jour: <span id="lastUpdate">--</span></div>
        </div>
        </div> <!-- Fin tab-realtime -->

        <!-- Contenu 24 heures -->
        <div id="tab-24h" class="tab-content">
            <div class="card" style="grid-column: 1 / -1;">
                <div class="card-title">📊 Historique 24 heures</div>
                <canvas id="history24hChart" class="history-chart"></canvas>
                <div class="card-label">Moyennes calculées sur 5 minutes</div>
            </div>
        </div>

        <!-- Contenu 7 jours -->
        <div id="tab-7d" class="tab-content">
            <div class="card" style="grid-column: 1 / -1;">
                <div class="card-title">📈 Historique 7 jours</div>
                <canvas id="history7dChart" class="history-chart"></canvas>
                <div class="card-label">Moyennes calculées par heure</div>
            </div>
        </div>

        <!-- Contenu 30 jours -->
        <div id="tab-30d" class="tab-content">
            <div class="card" style="grid-column: 1 / -1;">
                <div class="card-title">📉 Historique 30 jours</div>
                <canvas id="history30dChart" class="history-chart"></canvas>
                <div class="card-label">Moyennes calculées sur 4 heures</div>
            </div>
        </div>

    </div>

    <script>
        let autoRefresh = true;
        let refreshInterval = null;
        
        // Historique des débits (60 dernières valeurs = 5 minutes)
        let downloadHistory = [];
        let uploadHistory = [];
        const maxDataPoints = 60;
        
        // Fonction pour dessiner un graphique simple
        function drawChart(canvasId, data, color) {
            const canvas = document.getElementById(canvasId);
            if (!canvas) return;
            
            const ctx = canvas.getContext('2d');
            const width = canvas.width = canvas.offsetWidth;
            const height = canvas.height = 150;
            
            // Fond
            ctx.fillStyle = 'rgba(40, 42, 54, 0.5)';
            ctx.fillRect(0, 0, width, height);
            
            if (data.length < 2) return;
            
            // Trouver min/max pour l'échelle
            const max = Math.max(...data, 1);
            const padding = 20;
            
            // Dessiner la grille
            ctx.strokeStyle = 'rgba(98, 114, 164, 0.2)';
            ctx.lineWidth = 1;
            for (let i = 0; i <= 4; i++) {
                const y = padding + (height - 2 * padding) * i / 4;
                ctx.beginPath();
                ctx.moveTo(padding, y);
                ctx.lineTo(width - padding, y);
                ctx.stroke();
            }
            
            // Dessiner la courbe
            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            ctx.beginPath();
            
            const stepX = (width - 2 * padding) / (maxDataPoints - 1);
            const startIndex = Math.max(0, data.length - maxDataPoints);
            
            for (let i = 0; i < data.length - startIndex; i++) {
                const x = padding + i * stepX;
                const value = data[startIndex + i];
                const y = height - padding - ((value / max) * (height - 2 * padding));
                
                if (i === 0) {
                    ctx.moveTo(x, y);
                } else {
                    ctx.lineTo(x, y);
                }
            }
            
            ctx.stroke();
            
            // Zone sous la courbe
            ctx.lineTo(width - padding, height - padding);
            ctx.lineTo(padding, height - padding);
            ctx.closePath();
            ctx.fillStyle = color.replace(')', ', 0.1)').replace('rgb', 'rgba');
            ctx.fill();
            
            // Afficher la valeur max
            ctx.fillStyle = '#f8f8f2';
            ctx.font = '12px monospace';
            ctx.fillText(max.toFixed(2) + ' Mb/s', padding + 5, padding + 15);
        }
        
        // Fonction pour dessiner un graphique d'historique
        function drawHistoryChart(canvasId, data) {
            const canvas = document.getElementById(canvasId);
            if (!canvas || !data || data.length === 0) return;
            
            const ctx = canvas.getContext('2d');
            const width = canvas.width = canvas.offsetWidth;
            const height = canvas.height = 300;
            
            // Fond
            ctx.fillStyle = 'rgba(40, 42, 54, 0.8)';
            ctx.fillRect(0, 0, width, height);
            
            const padding = 50;
            const graphWidth = width - 2 * padding;
            const graphHeight = height - 2 * padding;
            
            // Trouver les valeurs max
            const maxDownload = Math.max(...data.map(d => d.download_max), 1);
            const maxUpload = Math.max(...data.map(d => d.upload_max), 1);
            const maxValue = Math.max(maxDownload, maxUpload);
            
            // Dessiner la grille
            ctx.strokeStyle = 'rgba(98, 114, 164, 0.2)';
            ctx.lineWidth = 1;
            for (let i = 0; i <= 4; i++) {
                const y = padding + graphHeight * i / 4;
                ctx.beginPath();
                ctx.moveTo(padding, y);
                ctx.lineTo(width - padding, y);
                ctx.stroke();
                
                // Labels Y
                ctx.fillStyle = '#6272a4';
                ctx.font = '12px monospace';
                ctx.fillText((maxValue * (4 - i) / 4).toFixed(1) + ' Mb/s', 5, y + 4);
            }
            
            // Dessiner la courbe download
            ctx.strokeStyle = '#50fa7b';
            ctx.lineWidth = 2;
            ctx.beginPath();
            
            data.forEach((point, i) => {
                const x = padding + (graphWidth * i / (data.length - 1));
                const y = height - padding - ((point.download_avg / maxValue) * graphHeight);
                
                if (i === 0) {
                    ctx.moveTo(x, y);
                } else {
                    ctx.lineTo(x, y);
                }
            });
            
            ctx.stroke();
            
            // Dessiner la courbe upload
            ctx.strokeStyle = '#8be9fd';
            ctx.lineWidth = 2;
            ctx.beginPath();
            
            data.forEach((point, i) => {
                const x = padding + (graphWidth * i / (data.length - 1));
                const y = height - padding - ((point.upload_avg / maxValue) * graphHeight);
                
                if (i === 0) {
                    ctx.moveTo(x, y);
                } else {
                    ctx.lineTo(x, y);
                }
            });
            
            ctx.stroke();
            
            // Légende
            ctx.fillStyle = '#50fa7b';
            ctx.fillRect(padding, 10, 20, 10);
            ctx.fillStyle = '#f8f8f2';
            ctx.font = '12px monospace';
            ctx.fillText('Download', padding + 25, 19);
            
            ctx.fillStyle = '#8be9fd';
            ctx.fillRect(padding + 120, 10, 20, 10);
            ctx.fillStyle = '#f8f8f2';
            ctx.fillText('Upload', padding + 145, 19);
        }
        
        // Fonction pour changer d'onglet
        function switchTab(tabName) {
            // Masquer tous les contenus
            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.remove('active');
            });
            
            // Désactiver tous les onglets
            document.querySelectorAll('.tab').forEach(tab => {
                tab.classList.remove('active');
            });
            
            // Activer l'onglet sélectionné
            document.getElementById(`tab-${tabName}`).classList.add('active');
            event.target.classList.add('active');
            
            // Charger les données d'historique si nécessaire
            if (tabName !== 'realtime') {
                loadHistory(tabName);
            }
        }
        
        // Fonction pour basculer en plein écran
        function toggleFullscreen() {
            if (!document.fullscreenElement) {
                document.documentElement.requestFullscreen().catch(err => {
                    console.log(`Erreur plein écran: ${err.message}`);
                });
            } else {
                if (document.exitFullscreen) {
                    document.exitFullscreen();
                }
            }
        }
        
        // Écouter la touche F pour le plein écran
        document.addEventListener('keydown', function(event) {
            if (event.key === 'f' || event.key === 'F') {
                event.preventDefault();
                toggleFullscreen();
            }
        });
        
        // Fonction pour charger l'historique
        async function loadHistory(period) {
            try {
                const response = await fetch(`/api/history/${period}`);
                const data = await response.json();
                
                if (data.success && data.data.length > 0) {
                    const canvasId = `history${period.replace('h', 'h').replace('d', 'd')}Chart`;
                    drawHistoryChart(canvasId, data.data);
                } else {
                    console.log('Pas encore assez de données pour', period);
                }
            } catch (error) {
                console.error('Erreur chargement historique:', error);
            }
        }

        function showError(message) {
            document.getElementById('errorText').textContent = message;
            document.getElementById('errorMessage').classList.add('show');
            document.getElementById('statusBadge').textContent = 'Hors ligne';
            document.getElementById('statusBadge').className = 'status-badge offline';
        }

        function hideError() {
            document.getElementById('errorMessage').classList.remove('show');
        }

        function formatBytes(bytes) {
            const gb = bytes / (1024 * 1024 * 1024);
            return gb.toFixed(2) + ' GB';
        }

        function formatUptime(seconds) {
            const days = Math.floor(seconds / 86400);
            const hours = Math.floor((seconds % 86400) / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            return `${days}j ${hours}h ${minutes}m`;
        }

        function updateProgress(elementId, percentage) {
            const element = document.getElementById(elementId);
            element.style.width = percentage + '%';
            element.textContent = Math.round(percentage) + '%';

            element.className = 'progress-fill';
            if (percentage > 80) {
                element.classList.add('danger');
            } else if (percentage > 60) {
                element.classList.add('warning');
            }
        }

        async function refreshData() {
            const refreshBtn = document.getElementById('refreshBtn');
            
            refreshBtn.disabled = true;
            document.getElementById('statusBadge').textContent = 'Actualisation...';
            document.getElementById('statusBadge').className = 'status-badge connecting';

            try {
                const response = await fetch('/api/status');
                
                if (!response.ok) {
                    throw new Error(`Erreur HTTP: ${response.status}`);
                }

                const data = await response.json();

                if (!data.success) {
                    throw new Error(data.error || 'Erreur inconnue');
                }

                hideError();

                const rxRateMbps = (data.stats.rx_rate * 8 / 1000000).toFixed(2);
                const txRateMbps = (data.stats.tx_rate * 8 / 1000000).toFixed(2);
                const bandwidthDown = (data.connection.bandwidth_down / 1000000).toFixed(0);
                const bandwidthUp = (data.connection.bandwidth_up / 1000000).toFixed(0);

                document.getElementById('downloadSpeed').textContent = rxRateMbps + ' Mb/s';
                document.getElementById('uploadSpeed').textContent = txRateMbps + ' Mb/s';
                document.getElementById('maxDownload').textContent = bandwidthDown + ' Mb/s';
                document.getElementById('maxUpload').textContent = bandwidthUp + ' Mb/s';

                // Mettre à jour l'historique des graphiques
                downloadHistory.push(parseFloat(rxRateMbps));
                uploadHistory.push(parseFloat(txRateMbps));
                
                // Limiter à maxDataPoints
                if (downloadHistory.length > maxDataPoints) {
                    downloadHistory.shift();
                    uploadHistory.shift();
                }
                
                // Redessiner les graphiques
                drawChart('downloadChart', downloadHistory, '#50fa7b');
                drawChart('uploadChart', uploadHistory, '#8be9fd');

                // Température - utiliser temp_avg calculé depuis sensors
                const tempAvg = data.system.temp_avg || 0;
                
                if (tempAvg === 0) {
                    document.getElementById('temperature').textContent = 'N/A';
                    document.getElementById('tempProgress').style.width = '0%';
                    document.getElementById('tempProgress').textContent = 'Non disponible';
                } else {
                    document.getElementById('temperature').textContent = `${tempAvg} °C`;
                    updateProgress('tempProgress', Math.min((tempAvg / 80) * 100, 100));
                }

                // Uptime - utiliser uptime_val (en secondes)
                if (data.system.uptime_val) {
                    document.getElementById('uptime').textContent = formatUptime(data.system.uptime_val);
                } else if (data.system.uptime) {
                    // Sinon utiliser le texte déjà formaté
                    document.getElementById('uptime').textContent = data.system.uptime;
                } else {
                    document.getElementById('uptime').textContent = '--';
                }

                document.getElementById('publicIP').textContent = data.connection.ipv4 || '--';
                document.getElementById('publicIPv6').textContent = data.connection.ipv6 || '--';
                document.getElementById('lineState').textContent = data.connection.state || '--';
                document.getElementById('connectionType').textContent = data.connection.type || '--';
                document.getElementById('connectionMedia').textContent = data.connection.media || '--';
                document.getElementById('bandwidth').textContent = `⬇️ ${bandwidthDown} / ⬆️ ${bandwidthUp} Mb/s`;

                document.getElementById('boardName').textContent = data.system.board_name || '--';
                document.getElementById('serial').textContent = data.system.serial || '--';
                document.getElementById('firmware').textContent = data.system.firmware_version || '--';

                document.getElementById('connectedDevices').textContent = data.lan.devices_active;
                document.getElementById('totalDevices').textContent = data.lan.devices_count;

                document.getElementById('rxBytes').textContent = formatBytes(data.stats.rx_bytes);
                document.getElementById('txBytes').textContent = formatBytes(data.stats.tx_bytes);

                // Informations WiFi
                document.getElementById('wifiEnabled').textContent = data.wifi.enabled ? '✅ Activé' : '❌ Désactivé';

                // Détails des Access Points WiFi
                const apDetailsDiv = document.getElementById('wifiAPDetails');
                apDetailsDiv.innerHTML = '';
                
                if (data.wifi.access_points && data.wifi.access_points.length > 0) {
                    data.wifi.access_points.forEach(ap => {
                        if (ap.config && ap.config.enabled && ap.status && ap.status.state === 'active') {
                            const apName = ap.name || 'Unknown';
                            const channel = ap.status.primary_channel || '--';
                            const channelWidth = ap.status.channel_width || '--';
                            
                            apDetailsDiv.innerHTML += `
                                <div class="info-row">
                                    <span class="info-label">${apName} - Canal ${channel}</span>
                                    <span class="info-value">${channelWidth} MHz</span>
                                </div>
                            `;
                        }
                    });
                }

                document.getElementById('statusBadge').textContent = 'En ligne';
                document.getElementById('statusBadge').className = 'status-badge';

                const now = new Date();
                document.getElementById('lastUpdate').textContent = now.toLocaleString('fr-FR');

            } catch (error) {
                console.error('Erreur:', error);
                showError(`Impossible de récupérer les données: ${error.message}`);
            } finally {
                refreshBtn.disabled = false;
            }
        }

        function startAutoRefresh() {
            refreshInterval = setInterval(refreshData, 5000);
        }

        function stopAutoRefresh() {
            if (refreshInterval) {
                clearInterval(refreshInterval);
                refreshInterval = null;
            }
        }

        refreshData();
        startAutoRefresh();

        document.addEventListener('visibilitychange', function() {
            if (document.hidden) {
                stopAutoRefresh();
            } else {
                refreshData();
                startAutoRefresh();
            }
        });
    </script>
</body>
</html>
"""

class FreeboxAPI:
    def __init__(self):
        self.session_token = None
        self.app_token = None
        self.challenge = None
        self.permissions = {}
        self.load_token()

    def load_token(self):
        """Charge le token depuis le fichier"""
        if os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, 'r') as f:
                    data = json.load(f)
                    self.app_token = data.get('app_token')
                    print(f"✓ Token chargé depuis {TOKEN_FILE}")
            except Exception as e:
                print(f"⚠ Erreur lors du chargement du token: {e}")

    def save_token(self, app_token):
        """Sauvegarde le token dans un fichier"""
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        
        with open(TOKEN_FILE, 'w') as f:
            json.dump({'app_token': app_token}, f)
        self.app_token = app_token
        print(f"✓ Token sauvegardé dans {TOKEN_FILE}")

    def request_authorization(self):
        """Demande l'autorisation d'accès à la Freebox"""
        url = f"{FREEBOX_URL}/api/v8/login/authorize"
        data = {
            "app_id": APP_ID,
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "device_name": DEVICE_NAME
        }
        
        try:
            response = requests.post(url, json=data, timeout=10)
            result = response.json()
            
            if result.get('success'):
                app_token = result['result']['app_token']
                track_id = result['result']['track_id']
                
                print("\n" + "="*60)
                print("🔐 AUTORISATION REQUISE")
                print("="*60)
                print(f"➤ Appuyez sur le bouton ► de votre Freebox Server")
                print(f"➤ Track ID: {track_id}")
                print("="*60 + "\n")
                
                status = self.wait_authorization(track_id)
                
                if status == 'granted':
                    self.save_token(app_token)
                    print("✓ Autorisation accordée !")
                    return True
                else:
                    print(f"✗ Autorisation refusée (status: {status})")
                    return False
            else:
                print(f"✗ Erreur: {result}")
                return False
                
        except Exception as e:
            print(f"✗ Erreur lors de la demande d'autorisation: {e}")
            return False

    def wait_authorization(self, track_id, timeout=120):
        """Attend que l'utilisateur accepte l'autorisation"""
        url = f"{FREEBOX_URL}/api/v8/login/authorize/{track_id}"
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                response = requests.get(url, timeout=10)
                result = response.json()
                
                if result.get('success'):
                    status = result['result']['status']
                    
                    if status == 'granted':
                        return 'granted'
                    elif status == 'pending':
                        print("⏳ En attente de validation...", end='\r')
                        time.sleep(2)
                    elif status == 'denied':
                        return 'denied'
                    elif status == 'timeout':
                        return 'timeout'
                        
            except Exception as e:
                print(f"✗ Erreur: {e}")
                time.sleep(2)
        
        return 'timeout'

    def login(self):
        """Se connecte à la Freebox et obtient un session_token"""
        if not self.app_token:
            print("⚠ Pas de token d'application. Demande d'autorisation...")
            if not self.request_authorization():
                return False

        try:
            url = f"{FREEBOX_URL}/api/v8/login"
            response = requests.get(url, timeout=10)
            result = response.json()
            
            if not result.get('success'):
                print(f"✗ Erreur lors de la récupération du challenge: {result}")
                return False
                
            self.challenge = result['result']['challenge']
            
            password = hmac.new(
                self.app_token.encode(),
                self.challenge.encode(),
                hashlib.sha1
            ).hexdigest()
            
            url = f"{FREEBOX_URL}/api/v8/login/session"
            data = {
                "app_id": APP_ID,
                "password": password
            }
            
            response = requests.post(url, json=data, timeout=10)
            result = response.json()
            
            if result.get('success'):
                self.session_token = result['result']['session_token']
                self.permissions = result['result']['permissions']
                print("✓ Connexion réussie à la Freebox")
                return True
            else:
                print(f"✗ Erreur de connexion: {result}")
                if result.get('error_code') == 'invalid_token':
                    if os.path.exists(TOKEN_FILE):
                        os.remove(TOKEN_FILE)
                    self.app_token = None
                return False
                
        except Exception as e:
            print(f"✗ Erreur lors de la connexion: {e}")
            return False

    def get_headers(self):
        return {'X-Fbx-App-Auth': self.session_token}

    def get_system_info(self):
        try:
            url = f"{FREEBOX_URL}/api/v8/system"
            response = requests.get(url, headers=self.get_headers(), timeout=10)
            result = response.json()
            
            if result.get('success'):
                # Extraire les températures du tableau sensors
                sensors = result['result'].get('sensors', [])
                
                # Chercher les températures dans les sensors
                temp_values = {}
                for sensor in sensors:
                    sensor_id = sensor.get('id', '')
                    if 'temp' in sensor_id.lower():
                        temp_values[sensor_id] = sensor.get('value', 0)
                
                # Ajouter les températures extraites au result
                result['result']['temp_sensors'] = temp_values
                
                # Calculer une température moyenne si disponible
                if temp_values:
                    avg_temp = sum(temp_values.values()) / len(temp_values)
                    result['result']['temp_avg'] = int(avg_temp)
                else:
                    result['result']['temp_avg'] = 0
            
            return result
        except Exception as e:
            print(f"✗ Erreur système: {e}")
            return None

    def get_connection_status(self):
        try:
            url = f"{FREEBOX_URL}/api/v8/connection"
            response = requests.get(url, headers=self.get_headers(), timeout=10)
            return response.json()
        except Exception as e:
            print(f"✗ Erreur connexion: {e}")
            return None

    def get_connection_stats(self):
        """Les stats sont dans connection_status, pas besoin d'endpoint séparé"""
        # L'endpoint /api/v8/connection/stats n'existe pas sur toutes les Freebox
        # Les statistiques sont disponibles dans /api/v8/connection directement
        return self.get_connection_status()

    def get_lan_hosts(self):
        try:
            url = f"{FREEBOX_URL}/api/v8/lan/browser/pub"
            response = requests.get(url, headers=self.get_headers(), timeout=10)
            return response.json()
        except Exception as e:
            print(f"✗ Erreur LAN: {e}")
            return None

    def get_wifi_status(self):
        """Récupère le status WiFi via config (compatible Freebox Ultra/Pop)"""
        try:
            url = f"{FREEBOX_URL}/api/v8/wifi/config"
            response = requests.get(url, headers=self.get_headers(), timeout=10)
            return response.json()
        except Exception as e:
            print(f"✗ Erreur WiFi: {e}")
            return None
    
    def get_wifi_ap(self):
        """Récupère les informations des points d'accès WiFi (Freebox Ultra)"""
        try:
            # Sur Freebox Ultra, il faut récupérer chaque AP individuellement
            # Les IDs sont : 0 (2.4G), 1 (5G), 10 (5G1), 11 (6G)
            ap_ids = [0, 1, 10, 11]
            access_points = []
            
            for ap_id in ap_ids:
                url = f"{FREEBOX_URL}/api/v8/wifi/ap/{ap_id}"
                response = requests.get(url, headers=self.get_headers(), timeout=10)
                result = response.json()
                
                if result.get('success') and 'result' in result:
                    access_points.append(result['result'])
            
            return {'success': True, 'result': access_points}
        except Exception as e:
            print(f"✗ Erreur WiFi AP: {e}")
            return None
    
    def get_wifi_stations(self):
        """Récupère la liste des stations WiFi connectées"""
        # L'endpoint /api/v8/wifi/stations n'existe pas sur Freebox Ultra
        # On retourne un résultat vide pour compatibilité
        return {'success': True, 'result': []}

freebox = FreeboxAPI()

@app.route('/')
def index():
    """Sert l'interface web"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/info')
def api_info():
    """Page d'accueil de l'API"""
    return jsonify({
        'name': 'Freebox Monitor API',
        'version': '1.0.0',
        'endpoints': [
            '/ - Interface web de monitoring',
            '/api/status - Récupère toutes les données',
            '/api/init - Initialise la connexion',
            '/api/info - Informations sur l\'API'
        ]
    })

@app.route('/api/status')
def get_status():
    """Endpoint pour récupérer toutes les données de monitoring"""
    
    # Vérifier si on a une session valide, sinon se reconnecter
    if not freebox.session_token:
        print("⚠️ Pas de session, reconnexion...")
        if not freebox.login():
            return jsonify({
                'success': False,
                'error': 'Impossible de se connecter à la Freebox'
            }), 500

    try:
        system_info = freebox.get_system_info()
        
        # Si on reçoit une erreur auth_required, le token a expiré
        if system_info and not system_info.get('success') and system_info.get('error_code') == 'auth_required':
            print("⚠️ Token expiré, reconnexion...")
            freebox.session_token = None
            if not freebox.login():
                return jsonify({
                    'success': False,
                    'error': 'Session expirée, impossible de se reconnecter'
                }), 500
            # Réessayer après reconnexion
            system_info = freebox.get_system_info()
        
        connection_status = freebox.get_connection_status()
        lan_hosts = freebox.get_lan_hosts()
        wifi_status = freebox.get_wifi_status()
        
        # Essayer de récupérer les infos WiFi avancées (peuvent échouer sur certains modèles)
        try:
            wifi_ap = freebox.get_wifi_ap()
            wifi_stations = freebox.get_wifi_stations()
        except:
            wifi_ap = None
            wifi_stations = None

        # Vérifier que les données essentielles sont valides
        if not system_info or not system_info.get('success'):
            return jsonify({
                'success': False,
                'error': 'Erreur lors de la récupération des informations système',
                'details': system_info
            }), 500
        
        if not connection_status or not connection_status.get('success'):
            return jsonify({
                'success': False,
                'error': 'Erreur lors de la récupération du statut de connexion',
                'details': connection_status
            }), 500

        data = {
            'success': True,
            'timestamp': time.time(),
            'system': {
                'uptime': system_info['result'].get('uptime', ''),
                'uptime_val': system_info['result'].get('uptime_val', 0),
                'temp_avg': system_info['result'].get('temp_avg', 0),
                'temp_sensors': system_info['result'].get('temp_sensors', {}),
                'temp_cpum': system_info['result'].get('temp_cpum', 0),
                'temp_sw': system_info['result'].get('temp_sw', 0),
                'temp_cpub': system_info['result'].get('temp_cpub', 0),
                'fan_rpm': system_info['result'].get('fan_rpm', 0),
                'board_name': system_info['result'].get('board_name', ''),
                'serial': system_info['result'].get('serial', ''),
                'firmware_version': system_info['result'].get('firmware_version', '')
            },
            'connection': {
                'state': connection_status['result'].get('state', ''),
                'type': connection_status['result'].get('type', ''),
                'media': connection_status['result'].get('media', ''),
                'ipv4': connection_status['result'].get('ipv4', ''),
                'ipv6': connection_status['result'].get('ipv6', ''),
                'rate_down': connection_status['result'].get('rate_down', 0),
                'rate_up': connection_status['result'].get('rate_up', 0),
                'bandwidth_down': connection_status['result'].get('bandwidth_down', 0),
                'bandwidth_up': connection_status['result'].get('bandwidth_up', 0)
            },
            'stats': {
                'rx_bytes': connection_status['result'].get('bytes_down', 0),
                'tx_bytes': connection_status['result'].get('bytes_up', 0),
                'rx_rate': connection_status['result'].get('rate_down', 0),
                'tx_rate': connection_status['result'].get('rate_up', 0)
            },
            'lan': {
                'devices_count': len(lan_hosts['result']) if lan_hosts and lan_hosts.get('success') else 0,
                'devices_active': len([d for d in lan_hosts['result'] if d.get('active', False)]) if lan_hosts and lan_hosts.get('success') else 0
            },
            'wifi': {
                'enabled': wifi_status['result'].get('enabled', False) if wifi_status and wifi_status.get('success') else False,
                'access_points': wifi_ap.get('result', []) if wifi_ap and wifi_ap.get('success') else [],
                'stations': wifi_stations.get('result', []) if wifi_stations and wifi_stations.get('success') else [],
                'stations_count': len(wifi_stations.get('result', [])) if wifi_stations and wifi_stations.get('success') else 0
            }
        }
        
        # Sauvegarder les stats dans la base de données
        download_mbps = (data['stats']['rx_rate'] * 8 / 1000000)
        upload_mbps = (data['stats']['tx_rate'] * 8 / 1000000)
        temp = data['system']['temp_avg']
        save_stats(download_mbps, upload_mbps, temp)

        return jsonify(data)
    
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"✗ Erreur dans get_status: {e}")
        print(error_trace)
        
        # Log détaillé pour debug
        print(f"Type d'erreur: {type(e).__name__}")
        print(f"Message: {str(e)}")
        
        return jsonify({
            'success': False,
            'error': f'Erreur serveur: {str(e)}',
            'error_type': type(e).__name__
        }), 500

@app.route('/api/init')
def init_freebox():
    """Endpoint pour initialiser la connexion"""
    if freebox.login():
        return jsonify({'success': True, 'message': 'Connexion établie'})
    else:
        return jsonify({'success': False, 'message': 'Échec de la connexion'}), 500

@app.route('/api/history/<period>')
def get_history(period):
    """Récupère l'historique pour une période donnée (24h, 7d, 30d)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        now = int(time.time())
        
        if period == '24h':
            start_time = now - (24 * 3600)
            # Grouper par 5 minutes
            interval = 300
        elif period == '7d':
            start_time = now - (7 * 24 * 3600)
            # Grouper par 1 heure
            interval = 3600
        elif period == '30d':
            start_time = now - (30 * 24 * 3600)
            # Grouper par 4 heures
            interval = 14400
        else:
            return jsonify({'success': False, 'error': 'Période invalide'}), 400
        
        # Récupérer les données agrégées
        cursor.execute('''
            SELECT 
                (timestamp / ?) * ? as period,
                AVG(download_rate) as avg_download,
                MAX(download_rate) as max_download,
                AVG(upload_rate) as avg_upload,
                MAX(upload_rate) as max_upload,
                AVG(temperature) as avg_temp
            FROM bandwidth_history
            WHERE timestamp >= ?
            GROUP BY period
            ORDER BY period ASC
        ''', (interval, interval, start_time))
        
        rows = cursor.fetchall()
        conn.close()
        
        data = {
            'success': True,
            'period': period,
            'data': [{
                'timestamp': int(row[0]),
                'download_avg': round(row[1], 2),
                'download_max': round(row[2], 2),
                'upload_avg': round(row[3], 2),
                'upload_max': round(row[4], 2),
                'temperature': round(row[5], 1) if row[5] else 0
            } for row in rows]
        }
        
        return jsonify(data)
        
    except Exception as e:
        print(f"✗ Erreur historique: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 Freebox Monitor API")
    print("="*60)
    
    # Initialiser la base de données
    init_database()
    
    # Nettoyer les anciennes données au démarrage
    cleanup_old_data()
    
    print("\n📡 Tentative de connexion à la Freebox...")
    freebox.login()
    
    print("\n🌐 Démarrage du serveur sur http://0.0.0.0:5000")
    print("📊 Interface web disponible sur http://localhost:5000")
    print("="*60 + "\n")
    
    app.run(host='0.0.0.0', port=5000, debug=False)
