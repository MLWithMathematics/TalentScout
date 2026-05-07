# TalentScout Deployment Plan: Render Free Tier + Neon

This guide covers the deployment architecture for the TalentScout Hiring Assistant using **Render's Free Tier (Manual Setup)** and **Neon (Serverless PostgreSQL)**. Since you are using the free version, we will bypass the Blueprint (`render.yaml`) and configure the service manually through the Render dashboard.

---

## 🏗️ Architecture Overview

- **Frontend**: Streamlit (Hosted on Render Web Service - Free Tier)
- **Database**: PostgreSQL (Hosted on Neon - Free Tier)
- **PII Encryption**: AES-128 Fernet
- **Deployment Method**: Render Dashboard (Manual Configuration)

---

## Phase 0: Generate Encryption Key

The application uses **Fernet symmetric encryption** to protect candidate PII (names, emails, phones) at rest. You must generate a secure key before starting.

1. **Run the Generator**:
   Open your terminal in the project directory and run:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
2. **Save the Key**:
   Copy the output (a string ending in `=`) and save it in your local `.env` file:
   ```env
   ENCRYPTION_KEY="your_copied_key_here"
   ```

> [!IMPORTANT]
> **Data Loss Warning:** If you change this key after you have already stored candidates in your database, you will **lose access** to their personal information forever. Always use the same key for both local development and production if they share the same database.

---

## Phase 1: Neon Database Setup (Free Tier)

Neon provides a fast, serverless PostgreSQL instance that pairs perfectly with Streamlit.

1. **Create an Account**: Go to [neon.tech](https://neon.tech) and sign up.
2. **Create a Project**: 
   - Name your project (e.g., `talentscout-db`).
   - Select the closest region to where your Render service will be hosted.
3. **Get the Connection String**:
   - Once the database is created, you will see a connection string on your dashboard.
   - It will look something like this: `postgresql://[user]:[password]@[endpoint].neon.tech/neondb?sslmode=require`.
   - **Copy this string.** You will need it for both local testing and production.

---

## Phase 2: Local Verification (Optional)

Before pushing to production, verify that your local code communicates correctly with Neon.

1. **Install Updated Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Update Environment Variables**:
   - Open your local `.env` file.
   - Add your Neon database URL:
     ```env
     DATABASE_URL="postgresql://[user]:[password]@[endpoint].neon.tech/neondb?sslmode=require"
     ```
3. **Test the App**:
   - Run the app: `streamlit run app.py`
   - The app will automatically connect to Neon and create the required tables.

---

## Phase 3: Manual Render Deployment (Free Tier)

We will set up the Web Service manually via the UI instead of using the `render.yaml` blueprint.

1. **Push Code to GitHub**:
   Make sure all your latest changes (`database.py`, `requirements.txt`) are pushed to your repository's `main` branch.

2. **Create a New Web Service**:
   - Log in to the [Render Dashboard](https://dashboard.render.com).
   - Click **New +** and select **Web Service**.
   - Choose **"Build and deploy from a Git repository"** and click Next.
   - Connect your GitHub account and select your `talentscout` repository.

3. **Configure the Service**:
   Fill in the form with the following details:
   - **Name**: `talentscout-hiring-assistant`
   - **Region**: (Choose the same region you used for Neon)
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`
   - **Instance Type**: Select the **Free** tier option.

4. **Add Environment Variables**:
   Scroll down to the **Environment Variables** section and click **Add Environment Variable**. Add the following:
   
   | Key | Value |
   | :--- | :--- |
   | `PYTHON_VERSION` | `3.11.0` |
   | `DATABASE_URL` | *(Paste your Neon connection string here)* |
   | `ENCRYPTION_KEY` | *(Paste the key you generated in Phase 0)* |
   | `ANTHROPIC_API_KEY` | *(Your Claude API key, if using Claude)* |
   | `GEMINI_API_KEY` | *(Your Gemini API key, if using Gemini)* |

5. **Deploy**:
   - Click **Create Web Service**.
   - Render will start building your app. It might take a few minutes on the free tier.
   - Once complete, your app will be live at a URL like `https://talentscout-hiring-assistant.onrender.com`.

---

## Phase 4: Production Verification

Once the app is live, verify that everything is working:

1. **Check the Live App**: Visit your new Render URL and ensure the Streamlit UI loads without errors.
2. **Data Ingestion**: Start a chat and provide dummy candidate details.
3. **Verify Neon**: Check your Neon SQL Editor to confirm a new row was inserted into the `candidates` table and that the PII columns are encrypted.
4. **Data Erasure**: Use the "Delete ALL My Data" button in the sidebar. Verify in Neon that the row is completely removed from the database.

> [!NOTE]
> **Spin-down Behavior:** Render's free web services spin down after 15 minutes of inactivity. The next time someone accesses the site, it will take about 50 seconds to wake up. This is expected behavior for the free tier.
