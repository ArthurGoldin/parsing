# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

barakaDataUZ is a microservices-based platform for collecting, processing, and providing analytical data about products and sales from Uzum marketplace. The system follows an event-driven architecture with Docker containerization.

## Core Architecture

### Microservices Structure

- **analytic_service**: FastAPI service for analytics, data processing, and RabbitMQ consumers
- **user_service**: FastAPI authentication service with PostgreSQL
- **image_service**: Async image processing service with Yandex S3 storage
- **parsing**: GraphQL-based web scraper for Uzum marketplace
- **celery_service**: Distributed task scheduler using Celery Beat
- **tgbot-service**: Telegram bot for proxy management (aiogram3)
- **api_gateway**: NGINX reverse proxy for service routing
- **frontend**: React/TypeScript SPA with Webpack

### Data Storage

- **PostgreSQL**: User data, transactions, subscriptions
- **ClickHouse**: Analytics data with daily partitioning (limit: 100 partitions per insert)
- **Redis**: Caching, parsing status, image keys, distributed locks
- **RabbitMQ**: Message queue for product data processing (batches of 1000)

## Development Commands

### Docker Management (use with sudo)

```bash
# Development
make build_up_dev     # Build and start dev containers
make up_dev          # Start existing dev containers
make stop_dev        # Stop dev containers
make full_reset_dev  # Complete reset with volume cleanup

# Production
make build_prod      # Build and start prod containers
make up_prod         # Start existing prod containers
make stop_prod       # Stop prod containers

# Utilities
make clean           # Docker system cleanup
make ps_all          # Show all container status
```

### Frontend Development

```bash
cd frontend/
npm start           # Start webpack dev server
npm run build       # Production build
```

### Database Operations

```bash
# Create superuser in user_service
sudo docker exec -it barakadatauz-user_service-1 bash -c "PYTHONPATH=/app python app/manage.py createsuperuser --email admin@admin.com --username admin"

# Run migrations
sudo docker exec -it barakadatauz-user_service-1 bash -c "PYTHONPATH=/app python app/manage.py makemigrations && python app/manage.py migrate"
```

## Key Technical Details

### Parsing System

- Daily automated parsing via Celery Beat (hourly checks, daily execution)
- GraphQL queries to Uzum API with proxy rotation
- Product variations treated as separate items
- Sales distribution calculated based on stock levels when marketplace provides only total sales
- Fake data generation available via `add_fake_data.py` (marked with `fake=True`)

### Data Processing Pipeline

1. Parsing service fetches products and sends to RabbitMQ in 1000-item batches
2. Analytics service consumers process queue and write to ClickHouse
3. Categories cached in Redis with different keys for frontend optimization
4. Images processed asynchronously and stored in Yandex S3

### Service Communication

- Internal Docker network communication on port 8000
- External access through NGINX gateway on ports 80/443
- RabbitMQ for async messaging between services
- Redis for caching and distributed coordination

## Environment Configuration

Each service requires .env file with specific variables. Critical variables include:

- JWT_SECRET_KEY (generate with `openssl rand -base64 32`)
- Database credentials (PostgreSQL, ClickHouse, MySQL for WordPress)
- RabbitMQ credentials
- Yandex S3 keys
- Telegram bot token and admin IDs

## Proxy Management

The `proxy_data/` directory contains proxy configurations used by both parsing and bot services. Structure:

```json
{
  "proxies": [
    {
      "ip": "1.2.3.4",
      "ports": { "http": 12345, "https": 12345 },
      "user": "username",
      "password": "password",
      "proxy_address": {
        "http": "username:password@host:port",
        "https": "username:password@host:port"
      },
      "exp": 2745250873,
      "status": "ACTIVE"
    }
  ]
}
```

## Common Issues

### ClickHouse Partitioning

- Max 100 partitions per insert (daily partitioning)
- Split large date range inserts to avoid errors
- Consider increasing limit in ClickHouse user profile for bulk operations

### NGINX Gateway

- Occasionally fails to start due to healthcheck dependencies
- Restart containers if gateway doesn't respond
- Ensure ports 80/443 are available on host

### Parsing Reliability

- Manual proxy rotation required (weekly)
- Failed parsing creates "snowball effect" with fake data generation
- Monitor Redis parsing status keys for debugging

## Recent Refactoring (2024)

### Comprehensive Parsing Module Refactoring

All Python modules in `parsing/app/` have been systematically refactored to implement robust software engineering patterns:

#### Core Improvements Applied

- **Utils Integration**: Created `utils/common.py` with shared utilities (logging, config, validation, retry logic)
- **Error Handling**: Replaced generic exceptions with specific types (`ValidationError`, `ConfigurationError`, `ConnectionError`)
- **Input Validation**: Comprehensive parameter validation with meaningful error messages
- **Exponential Backoff**: Implemented proper retry strategies with configurable delays
- **Resource Management**: Added context managers and proper cleanup in finally blocks
- **Logging Enhancement**: Consistent logging patterns with appropriate levels and context
- **Configuration Validation**: Robust config loading with required section/key validation
- **Connection Management**: Proper timeouts, connection pooling, and graceful degradation

#### Refactored Modules

1. **`utils/common.py`** - New shared utilities module with:

   - `setup_logger()` - Consistent logging configuration
   - `load_and_validate_config()` - Config validation with error handling
   - `exponential_backoff()` - Retry logic with jitter
   - `validate_network_config()` - Network parameter validation
   - Custom exception classes and validation functions

2. **`send_data_to_db.py`** - Fixed RabbitMQ encoding error (`'NoneType' object has no attribute 'encode'`) and enhanced:

   - Added data validation before sending to RabbitMQ
   - Implemented connection pooling and retry logic
   - Enhanced error categorization and logging
   - Added comprehensive input validation

3. **`product_fetcher.py`** - Enhanced with utils integration:

   - Removed code duplication by using shared utilities
   - Added network configuration validation
   - Improved GraphQL query handling and response validation
   - Enhanced batch processing with better error recovery

4. **`main.py`** - Complete rewrite with `ParsingOrchestrator` class:

   - Robust module chaining with comprehensive error handling
   - Detailed execution reporting and progress tracking
   - Graceful failure handling with rollback capabilities
   - Enhanced logging and diagnostics

5. **`save_and_load_data.py`** - Enhanced file operations:

   - Added file size limits (100MB) and security validations
   - Improved JSON/CSV handling with structure validation
   - Enhanced directory creation with proper permissions
   - Better error categorization and recovery

6. **`system_check.py`** - Enhanced with `SystemDiagnostics` class:

   - Comprehensive health checking and system info collection
   - Network connectivity tests with proper timeouts
   - Performance benchmarks and resource monitoring
   - Detailed reporting with execution summaries

7. **`ids_fetcher.py`** - Refactored for robustness:

   - Enhanced GraphQL query handling with retry logic
   - Improved batch processing and progress tracking
   - Better error handling and category failure tracking
   - Added comprehensive input validation

8. **`proxy_manager.py`** - Enhanced proxy management:

   - Improved connection handling with timeouts
   - Better proxy rotation and health checking
   - Enhanced scheduler management and cleanup
   - Added comprehensive logging and error recovery

9. **`token_manager.py`** - Robust token management:

   - Enhanced Selenium integration with better error handling
   - Improved token validation and refresh logic
   - Better WebDriver management with cleanup
   - Added comprehensive retry mechanisms

10. **`brands_crawler.py`** - Complete refactor:

    - Enhanced Selenium WebDriver management with context managers
    - Improved captcha handling and page loading logic
    - Better HTML parsing with multiple selector fallbacks
    - Added comprehensive error handling and progress tracking

11. **`image_download.py`** - Enhanced image processing:

    - Robust HTTP client with retry strategies
    - Enhanced Redis integration with connection pooling
    - Better file validation and security checks
    - Improved upload handling with comprehensive error recovery

12. **`root_categories.py`** - Enhanced category management:
    - Improved GraphQL and REST API handling
    - Better multi-language support with error handling
    - Enhanced data structure validation and processing
    - Improved connection management and resource cleanup

#### Key Patterns Implemented

- **Validation-First Approach**: All functions validate inputs before processing
- **Graceful Degradation**: Functions continue operation when possible, with fallbacks
- **Comprehensive Logging**: Detailed logging at appropriate levels with context
- **Resource Safety**: Proper cleanup in finally blocks and context managers
- **Error Categorization**: Specific exception types for different failure modes
- **Retry Logic**: Exponential backoff with jitter for network operations
- **Configuration Management**: Centralized config validation with meaningful errors
- **Progress Tracking**: Detailed progress reporting for long-running operations

#### Benefits Achieved

- **Reliability**: Fixed critical RabbitMQ encoding issue and improved error recovery
- **Maintainability**: Consistent patterns across all modules with shared utilities
- **Observability**: Enhanced logging and diagnostics for better debugging
- **Robustness**: Comprehensive error handling and input validation
- **Performance**: Better resource management and connection pooling
- **Backward Compatibility**: All refactoring maintains existing APIs and functionality

## File Locations

- Service-specific requirements: `{service}/requirements.txt`
- Frontend dependencies: `frontend/package.json`
- Database schemas: `analytic_service/alembic/versions/`
- GraphQL queries: `parsing/app/GraphQL/`
- ClickHouse schemas: `analytic_service/clickhouse/`
- Parsing utilities: `parsing/app/utils/common.py`
