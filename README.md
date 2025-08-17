![Marketplace logo](./images/logo.png)

# Marketplace Parser for [Uzum market](https://uzum.uz)

## 🐍 Virtual Environment Setup

This project uses a Python virtual environment to manage dependencies. Here are several ways to automatically activate it:

### Option 1: VS Code Workspace (Recommended)

Open the project in VS Code using the `parsing.code-workspace` file. The virtual environment will be automatically activated.

### Option 2: Using the Activation Script

```bash
# Activate virtual environment and set up environment
source activate.sh
```

### Option 3: Using direnv (Advanced)

1. Install direnv: `brew install direnv` (macOS) or `sudo apt install direnv` (Ubuntu)
2. Add to your shell: `echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc` (or bash)
3. Allow the project: `direnv allow`
4. The virtual environment will activate automatically when you enter the directory

### Option 4: Using Make

```bash
# Install dependencies
make install

# Run the application
make run

# See all available commands
make help
```

### Manual Activation

If you prefer manual activation:

```bash
source .venv/bin/activate
```

## Running the Modules Locally

1. Navigate to the `app` folder:

   ```bash
   cd app
   ```

2. Run the following scripts:

   - To check all modules:

     ```bash
     python3 system_check.py
     ```

   - To start parsing the marketplace:

     ```bash
     python3 main.py
     ```

   - To fetch all categories in a JSON file with a tree hierarchy:

     ```bash
     python3 root_categories.py
     ```

   - To fetch all product IDs for categories passed as arguments (provide category ID numbers as arguments):
     ```bash
     python3 product_ids.py <category_id>
     ```

3. If for some reason your Google Chrome is outdated, you'll get an error:

   ```bash
   Error in get_token_instance: Message: session not created: cannot connect to chrome at XXX.X.X.X:XXXXX
   from session not created: This version of ChromeDriver only supports Chrome version YYY
   ```

   Update your Google Chrome by following the [instructions](https://support.google.com/chrome/answer/95414?hl=en&co=GENIE.Platform%3DDesktop).

## Docker Instructions

1. Build the Docker image:

   ```bash
   docker build -t uzum_parser .
   ```

2. To run the `main` module:

   ```bash
   docker run --network barakadatauz_app-network -v $(pwd)/app/configs:/app/configs -v $(pwd)/app/data:/app/data -v $(pwd)/app/logs:/app/logs -p 8001:8000 --name parser uzum_parser
   ```

   This will mount the host's `app/data` and `app/logs` directories to the container’s `/app/data` and `/app/logs` directories. Update host directories as necessary. Change or remove port values as needed.

3. To run a specific module:

   ```bash
   docker run -network barakadatauz_app-network -v $(pwd)/app/configs:/app/configs -v $(pwd)/app/data:/app/data -v $(pwd)/app/logs:/app/logs uzum_parser python3 -m <module_name>
   ```

4. RabbitMQ Messaging to the Baraka App:

   - Without specifying a container name:

     ```bash
     docker run --network barakadatauz_app-network -v $(pwd)/app/configs:/app/configs -v $(pwd)/app/data:/app/data -v $(pwd)/app/logs:/app/logs uzum_parser python3 -m <module_name>
     ```

   - With a specified container name:
     ```bash
     docker run --name <my_container_name> --network barakadatauz_app-network -v $(pwd)/app/configs:/app/configs -v $(pwd)/app/data:/app/data -v $(pwd)/app/logs:/app/logs uzum_parser python3 -m <module_name>
     ```

- Consider different port numbers if needed.
- Check ports.
