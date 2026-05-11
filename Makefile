# ============================================================
# LocalAI TV - Makefile for Docker management
# ============================================================

.PHONY: help build up down restart logs ps clean test health

help:
	@echo "LocalAI TV - Docker Management"
	@echo ""
	@echo "Available commands:"
	@echo "  make build     - Build Docker image"
	@echo "  make up        - Start all services"
	@echo "  make down      - Stop all services"
	@echo "  make restart   - Restart all services"
	@echo "  make logs      - View logs"
	@echo "  make ps        - Show running containers"
	@echo "  make clean     - Remove containers and volumes"
	@echo "  make test      - Run tests"
	@echo "  make health    - Check health endpoint"

# Build the Docker image
build:
	docker build -t localaitv:latest .

# Start all services (development)
up:
	docker-compose up -d

# Stop all services
down:
	docker-compose down

# Restart all services
restart:
	docker-compose restart

# View logs
logs:
	docker-compose logs -f

# Show running containers
ps:
	docker-compose ps

# Clean up everything
clean:
	docker-compose down -v
	docker system prune -f

# Run tests
test:
	docker-compose run --rm app python -c "import webhook_server; print('Tests passed!')"

# Check health endpoint
health:
	@curl -s http://localhost:8000/health | python3 -m json.tool

# Build production image
build-prod:
	docker build -t localaitv:latest . --target production

# Production deployment
up-prod:
	docker-compose -f docker-compose.prod.yml up -d

down-prod:
	docker-compose -f docker-compose.prod.yml down

logs-prod:
	docker-compose -f docker-compose.prod.yml logs -f

# SSH into container
shell:
	docker exec -it localaitv_app sh

# Pull latest from registry
pull:
	docker pull ghcr.io/$(shell git remote get-url origin | sed 's|.*/||' | sed 's|\.git||')/localaitv:latest || true

# ============================================================
# Monitoring Commands
# ============================================================

# Start with monitoring stack
up-monitor:
	docker-compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d

# Stop monitoring
down-monitor:
	docker-compose -f docker-compose.yml -f docker-compose.monitoring.yml down

# View Prometheus logs
logs-prom:
	docker-compose -f docker-compose.monitoring.yml logs -f prometheus

# View Grafana logs
logs-grafana:
	docker-compose -f docker-compose.monitoring.yml logs -f grafana

# View Loki logs
logs-loki:
	docker-compose -f docker-compose.monitoring.yml logs -f loki

# Access Grafana
grafana:
	@echo "Grafana: http://localhost:3000"
	@echo "  User: admin"
	@echo "  Pass: admin123"

# Access Prometheus
prometheus:
	@echo "Prometheus: http://localhost:9090"

# Access Loki (logs)
loki:
	@echo "Loki API: http://localhost:3100"

# View app logs in Loki format
logs-app:
	docker-compose -f docker-compose.monitoring.yml logs -f app | grep -v "GOVERNOR\|TICKER\|INFO\|⚠️\|✓\|🔄\|🎙\|DB\|[assets]"

# Clean monitoring data
clean-monitor:
	docker-compose -f docker-compose.monitoring.yml down -v
	rm -rf monitoring/prometheus_data monitoring/grafana_data monitoring/loki_data monitoring/alertmanager_data 2>/dev/null || true