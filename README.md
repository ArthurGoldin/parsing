# Marketplace parser for https://uzum.uz

- If you want to run modules locally, cd to the app folder.

- Run system_check.py to check all modules.

- Run main.py to start parsing the marketplace.

- Run root_categories.py to fetch all categories in json file with a tree hierarchy.

- Run product_ids.py to fetch all product IDs for categories sent to the command as arguments (add category ID numbers as argument).

## Docker instructions

1. Build docker image:
   - `docker build -t uzum_parser .`
2. To run the 'main' module:
   - `docker run -v $(pwd)/app/data:/app/data -v $(pwd)/app/logs:/app/logs -p 8000:8000 --name parser uzum_parser`
   - `This will mount the host's 'app/data' and 'app/logs' directories to the container’s /app/data  and '/app/logs' directories. Update host directories as needed`
   - `Change/remove port values as needed`
3. To run a specific module:
   - `docker run -v $(pwd)/app/data:/app/data -v $(pwd)/app/logs:/app/logs uzum_parser python3 -m <module_name>`
4. RabbitMQ messaging to the baraka app:
   - `docker run --network barakadatauz_app-network -v $(pwd)/app/data:/app/data -v $(pwd)/app/logs:/app/logs uzum_parser python3 -m <module_name>`
   - `or with specified container name`
   - `docker run --name my_container_name --network barakadatauz_app-network -v $(pwd)/app/data:/app/data -v $(pwd)/app/logs:/app/logs uzum_parser python3 -m <module_name>`
