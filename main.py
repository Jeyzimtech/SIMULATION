from fastapi import FastAPI, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
import subprocess
import os

app = FastAPI(title="Solar-Thermal Simulation API")

# Mount the webapp directory so that the HTML/CSS/JS is served
app.mount("/webapp", StaticFiles(directory="webapp", html=True), name="webapp")

@app.get("/")
def read_root():
    # Redirect the root URL to the web app dashboard
    return RedirectResponse(url="/webapp/")

@app.get("/simulation_results.csv")
def get_csv():
    file_path = "simulation_results.csv"
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="text/csv")
    return {"error": "CSV File not found. Run the simulation first."}

@app.get("/simulation_graphs.png")
def get_png():
    file_path = "simulation_graphs.png"
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="image/png")
    return {"error": "Graph Image not found. Run the simulation first."}

@app.post("/api/run-simulation")
def run_simulation_endpoint(background_tasks: BackgroundTasks):
    """
    Endpoint to trigger the Python simulation to run in the background.
    """
    def run_sim():
        subprocess.run(["python", "solar_simulation.py"])
    
    background_tasks.add_task(run_sim)
    return {"message": "Simulation started in the background. Refresh the data later."}
