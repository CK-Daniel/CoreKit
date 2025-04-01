# How to Commit Feature Updates

This guide explains how to commit and push feature updates to the `CoreKit` repository using the Personal Access Token embedded in the remote URL.

**Note:** Embedding tokens directly in the remote URL is generally **not recommended** for security reasons. If the URL is exposed (e.g., in logs or shared configurations), your token could be compromised. Consider using more secure methods like Git credential helpers or SSH keys if possible.

## Steps

1.  **Stage Your Changes:**
    Make sure all the changes you want to include in the update are staged. You can stage all changes in the current directory using:
    ```bash
    git add .
    ```
    Or stage specific files:
    ```bash
    git add path/to/your/file.ext
    ```

2.  **Commit Your Changes:**
    Create a commit with a descriptive message explaining the changes:
    ```bash
    git commit -m "feat: Add new feature X"
    ```
    Replace `"feat: Add new feature X"` with your actual commit message.

3.  **Push Your Changes:**
    Push the commit to the `master` branch on the remote repository (`origin`). Since the token is embedded in the remote URL, Git should authenticate automatically.
    ```bash
    git push origin master
    ```

    *The remote `origin` for this project is currently configured as:*
    `https://[YOUR_TOKEN]@github.com/CK-Daniel/CoreKit.git`
    *(Replace `[YOUR_TOKEN]` with the actual token if you ever need to reconfigure the remote manually)*

That's it! Your changes should now be reflected in the GitHub repository.
