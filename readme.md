# XING/Join Automated Scraper & GPT Resume Builder

This project automates the following processes:

1. **Collecting job listings from XING** (saving to CSV).
2. **Evaluating job relevance via GPT** (OpenAI ChatCompletion).
3. **Automatically applying to jobs** (Easy Apply, Chat, or External).
4. **Generating PDF resumes** with GPT and WeasyPrint, tailored to each job description.

Additionally, it includes examples for join.com (handling partially filled applications) and adesso.com.

---

## Project Structure

```
xing_automation/
├─ main.py
├─ config.py
├─ gpt.py
├─ migrate.py
├─ clean_job_list.py
├─ collect_stat.py
├─ resume.yaml
├─ resume_buld_test.py
├─ styles.css
├─ requirements.txt
├─ README.txt
├─ generated_pdfs/
├─ scrapers/
│   ├─ xing.py
│   ├─ join.py
│   ├─ adesso.py
│   ├─ gpt_resume_builder.py
│   ├─ utils.py
│   ├─ prompts.py
│   └─ prompts/
│       └─ (text prompt files)
└─ (other files or folders)
```

- **main.py**: Entry point with a simple menu (1. collect → 2. GPT-evaluate → 3. apply).
- **config.py**: Project configuration (file paths, credentials, API keys).
- **gpt.py**: Logic to evaluate job relevance (OpenAI).
- **migrate.py**: Migrates data from stats.csv to job_listings.csv.
- **clean_job_list.py**: Cleans duplicates in CSV.
- **collect_stat.py**: Basic analysis (top domains, unique links).
- **resume.yaml**: Example of candidate data in YAML (personal info, skills, etc.).
- **resume_buld_test.py**: Tests generating a PDF resume with GPT & WeasyPrint.
- **styles.css**: CSS for generated PDF.
- **scrapers/**: Contains scrapers for XING, join, adesso, plus utility modules.
- **generated_pdfs/**: Stores generated PDF files.

---

## Installation

1. **Clone** the repository:
   ```sh
   git clone https://github.com/<username>/xing-automation.git
   cd xing-automation
   ```

2. **(Optional) Create a virtual environment**:
   ```sh
   python -m venv .venv
   source .venv/bin/activate  # On Linux / Mac
   .venv\Scripts\activate  # On Windows
   ```

3. **Install dependencies**:
   ```sh
   pip install -r requirements.txt
   ```
   Or install modules individually:
   ```sh
   pip install playwright openai weasyprint langdetect pyyaml deep-translator
   ```

4. **(Optional) Install Playwright browsers**:
   ```sh
   playwright install
   ```

5. **Update `config.py`**:
   - Set your `OPENAI_API_KEY`.
   - Enter your XING login/password.
   - Adjust any file paths if needed.

---

## Usage

Simply run `main.py`:

```sh
python main.py
```

You will see a menu like:

```
1 - Collect jobs (XING)
2 - GPT relevance evaluation
3 - Auto-apply on XING
4 - All steps (1 -> 2 -> 3)
0 - Exit
```

- **Collect**: scrapes XING job listings into `job_listings.csv`.
- **Evaluate**: uses GPT to score and comment (GPT_Score, GPT_Reason).
- **Apply**: automatically applies to selected jobs (Easy Apply), or marks external links.

---

## Resume Data

- **`resume.yaml`**: Contains your personal details, skills, experience, etc.
- **`resume_buld_test.py`**: Shows how to generate a PDF resume (GPT + WeasyPrint).
- For a minimal example, see `EXAMPLE_RESUME.yaml` or the main `resume.yaml`.

---

## Contributing

Pull requests are welcome. For large changes, open an issue first to discuss your ideas.

---

## License

Licensed under the MIT License (see `LICENSE.txt` for details).
