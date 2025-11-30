#!/bin/bash

# Script de démarrage pour Freebox Monitor

echo "=========================================="
echo "            📊 Freebox Monitor            "
echo "=========================================="
echo ""

# Créer le dossier data s'il n'existe pas
if [ ! -d "data" ]; then
    echo "📁 Création du dossier data..."
    mkdir -p data
fi

# Vérifier si Docker est installé
if ! command -v docker &> /dev/null; then
    echo "❌ Docker n'est pas installé"
    echo "   Installez Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

# Vérifier si docker-compose est installé
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose n'est pas installé"
    echo "   Installez Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker et Docker Compose sont installés"
echo ""

# Arrêter les anciens conteneurs si nécessaire
if [ "$(docker ps -q -f name=freebox-monitor)" ]; then
    echo "🛑 Arrêt de l'ancien conteneur..."
    docker-compose down
fi

# Construire l'image
echo "🔨 Construction de l'image Docker..."
docker-compose build

# Lancer le conteneur
echo "🚀 Démarrage du conteneur..."
docker-compose up -d

echo ""
echo "=========================================="
echo "✅ Conteneur démarré avec succès!"
echo "=========================================="
echo ""
echo "📊 Interface web: http://localhost:5000"
echo "🔧 API: http://localhost:5000/api/status"
echo ""
echo "📝 Commandes utiles:"
echo "   docker-compose logs -f          # Voir les logs"
echo "   docker-compose restart          # Redémarrer"
echo "   docker-compose down             # Arrêter"
echo "   docker-compose ps               # Statut"
echo ""
echo "🔐 IMPORTANT:"
echo "   Au premier lancement, appuyez sur le bouton ►"
echo "   de votre Freebox Server pour autoriser l'accès."
echo "   Consultez les logs avec: docker-compose logs -f"
echo ""
echo "=========================================="

# Afficher les logs en temps réel
echo "📋 Affichage des logs (Ctrl+C pour quitter)..."
echo ""
sleep 2
docker-compose logs -f
