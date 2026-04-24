import math
import csv
import os

try:
    import matplotlib
    matplotlib.use('Agg')
    import pandas as pd
    import matplotlib.pyplot as plt
    PLOTTING_AVAILABLE = True
except ImportError:
    PLOTTING_AVAILABLE = False

class HeatRecoveryModule:
    """Pre-Filtration & Heat Recovery Unit."""
    def __init__(self, effectiveness=0.85):
        self.effectiveness = effectiveness

    def step(self, m_dot_cold, t_cold_in, m_dot_hot, t_hot_in, dt):
        cp_water = 4184    # J/(kg*K)
        h_vap = 2260000    # J/kg
        
        q_available = m_dot_hot * h_vap * dt
        max_q = m_dot_cold * cp_water * (t_hot_in - t_cold_in) * dt
        
        if max_q <= 0 or q_available <= 0:
            return t_cold_in, 0.0

        q_transfer = min(q_available, max_q) * self.effectiveness
        
        t_cold_out = t_cold_in + (q_transfer / (m_dot_cold * cp_water * dt)) if m_dot_cold > 0 else t_cold_in
        m_dot_condensed_out = min(m_dot_hot, q_transfer / (h_vap * dt)) if dt > 0 else 0
        
        return t_cold_out, m_dot_condensed_out

class CSPModule:
    """Solar Concentrator."""
    def __init__(self, area=5.0, efficiency=0.7):
        self.area = area
        self.efficiency = efficiency

    def step(self, time_of_day_hours, cloud_factor=1.0):
        # Time 0 is midnight. Sunrise at 6, Sunset at 18
        if 6 <= time_of_day_hours <= 18:
            dni = 1000 * math.sin(math.pi * (time_of_day_hours - 6) / 12)
        else:
            dni = 0
            
        q_thermal = dni * self.area * self.efficiency * cloud_factor
        return q_thermal

class ParrafinBatteryModule:
    """PCM Thermal Storage."""
    def __init__(self, mass=80, t_melt=85, cp_solid=2100, cp_liquid=2400, h_fusion=210000):
        self.mass = mass
        self.t_melt = t_melt
        self.cp_solid = cp_solid
        self.cp_liquid = cp_liquid
        self.h_fusion = h_fusion
        
        self.t_pcm = 25.0
        self.melt_fraction = 0.0

    def step(self, q_in, q_out, dt):
        q_net = q_in - q_out
        energy_change = q_net * dt
        
        if self.t_pcm < self.t_melt:
            self.t_pcm += energy_change / (self.mass * self.cp_solid)
            if self.t_pcm > self.t_melt:
                excess_energy = (self.t_pcm - self.t_melt) * (self.mass * self.cp_solid)
                self.t_pcm = self.t_melt
                self.melt_fraction += excess_energy / (self.mass * self.h_fusion)
        elif self.t_pcm == self.t_melt:
            self.melt_fraction += energy_change / (self.mass * self.h_fusion)
            if self.melt_fraction > 1.0:
                excess_energy = (self.melt_fraction - 1.0) * (self.mass * self.h_fusion)
                self.melt_fraction = 1.0
                self.t_pcm += excess_energy / (self.mass * self.cp_liquid)
            elif self.melt_fraction < 0.0:
                deficit_energy = (0.0 - self.melt_fraction) * (self.mass * self.h_fusion)
                self.melt_fraction = 0.0
                self.t_pcm -= deficit_energy / (self.mass * self.cp_solid)
        else:
            self.t_pcm += energy_change / (self.mass * self.cp_liquid)
            if self.t_pcm < self.t_melt:
                deficit_energy = (self.t_melt - self.t_pcm) * (self.mass * self.cp_liquid)
                self.t_pcm = self.t_melt
                self.melt_fraction -= deficit_energy / (self.mass * self.h_fusion)

        return self.t_pcm

class BoilerModule:
    """Distillation Chamber."""
    def __init__(self):
        self.water_mass = 5.0 # initial kg
        self.t_water = 25.0
        self.tds_ppm = 1000.0 # Initial salinity
        self.cp_water = 4184
        self.h_vap = 2260000
    
    def get_heat_transfer(self, t_pcm, U_coeff=150.0):
        if t_pcm > self.t_water:
            return U_coeff * (t_pcm - self.t_water)
        return 0.0

    def step(self, feed_mass, feed_temp, q_in, dt):
        if feed_mass > 0:
            new_mass = self.water_mass + feed_mass
            if new_mass > 0:
                self.t_water = (self.water_mass * self.t_water + feed_mass * feed_temp) / new_mass
                total_tds = (self.water_mass * self.tds_ppm) + (feed_mass * 1000.0)
                self.tds_ppm = total_tds / new_mass
            self.water_mass = new_mass

        m_dot_steam = 0.0
        energy_in = q_in * dt
        if self.water_mass > 0:
            self.t_water += energy_in / (self.water_mass * self.cp_water)
        
        if self.t_water >= 100.0:
            excess_energy = (self.t_water - 100.0) * (self.water_mass * self.cp_water)
            self.t_water = 100.0
            steam_mass = excess_energy / self.h_vap
            
            if steam_mass > self.water_mass:
                steam_mass = self.water_mass
                
            self.water_mass -= steam_mass
            m_dot_steam = steam_mass / dt
            
            if self.water_mass > 0:
                total_salt = (self.water_mass + steam_mass) * self.tds_ppm
                self.tds_ppm = total_salt / self.water_mass

        return m_dot_steam, self.t_water

class SupervisoryController:
    """Automation Logic."""
    def __init__(self):
        self.pump_on = False
        self.inlet_valve_open = False
        self.drain_valve_open = False
        self.fractional_valve_dest = "VENT"

    def execute(self, boiler_level, steam_temp, boiler_tds):
        # Level control
        if boiler_level < 3.0:
            self.pump_on = True
            self.inlet_valve_open = True
        elif boiler_level > 15.0:
            self.pump_on = False
            self.inlet_valve_open = False
            
        # Venting
        if steam_temp < 100.0:
            self.fractional_valve_dest = "VENT"
        else:
            self.fractional_valve_dest = "CONDENSER"
            
        # Flushing logic (simulating sludge drain)
        if boiler_tds > 10000.0: # 10,000 ppm limit
            self.drain_valve_open = True
            self.pump_on = True # Flush with fresh water
        else:
            self.drain_valve_open = False

def run_simulation(days=3):
    print("Initializing Solar-Thermal Distillation Simulation...")
    csp = CSPModule(area=8.0) 
    pcm = ParrafinBatteryModule(mass=120) 
    boiler = BoilerModule()
    heat_recv = HeatRecoveryModule()
    controller = SupervisoryController()
    
    dt = 60 # 1 minute steps
    total_steps = int((days * 24 * 3600) / dt)
    feed_flow_rate = 0.1 # kg/s when pump is on
    ambient_temp = 25.0
    
    total_distilled = 0.0
    history = []
    
    for step in range(total_steps):
        time_seconds = step * dt
        time_hours = (time_seconds / 3600) % 24
        total_time_hr = time_seconds / 3600.0
        
        # 1. Controller Execute
        controller.execute(
            boiler_level=boiler.water_mass,
            steam_temp=boiler.t_water,
            boiler_tds=boiler.tds_ppm
        )
        
        # Actions applied
        if controller.drain_valve_open:
            boiler.water_mass = max(0.1, boiler.water_mass - 0.5 * dt)
            
        m_dot_feed = feed_flow_rate if controller.pump_on and controller.inlet_valve_open else 0.0
        feed_mass = m_dot_feed * dt
        
        # 2. Thermal Environment
        q_solar = csp.step(time_hours)
        q_to_boiler = boiler.get_heat_transfer(pcm.t_pcm)
        
        pcm.step(q_in=q_solar, q_out=q_to_boiler, dt=dt)
        m_dot_steam, t_steam = boiler.step(feed_mass, ambient_temp, q_to_boiler, dt)
        
        # 3. Heat Recovery / Conversion
        condensed_rate = 0.0
        if controller.fractional_valve_dest == "CONDENSER" and m_dot_steam > 0:
            # Simplified recovery (preheats incoming but returns condensed vol)
            _, condensed_rate = heat_recv.step(max(0.001, m_dot_feed), ambient_temp, m_dot_steam, t_steam, dt)
            total_distilled += condensed_rate * dt
            
        history.append({
            "time_hr": total_time_hr,
            "q_solar_kw": q_solar / 1000.0,
            "t_pcm": pcm.t_pcm,
            "pcm_melt": pcm.melt_fraction,
            "t_boiler": boiler.t_water,
            "boiler_vol": boiler.water_mass,
            "tds_ppm": boiler.tds_ppm,
            "total_distilled_L": total_distilled
        })

    # Save to CSV
    csv_file = "simulation_results.csv"
    with open(csv_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=history[0].keys())
        writer.writeheader()
        writer.writerows(history)
        
    print(f"Simulation completed! Total Distilled Water over {days} days: {total_distilled:.2f} Liters")
    print(f"Data saved to {csv_file}")
    
    if PLOTTING_AVAILABLE:
        print("Generating visualization graphs...")
        plot_results(csv_file)
    else:
        print("matplotlib/pandas not found. Skipping plot generation.")

def plot_results(csv_file):
    df = pd.read_csv(csv_file)
    fig, axs = plt.subplots(4, 1, figsize=(10, 14))
    
    axs[0].plot(df['time_hr'], df['t_pcm'], label='PCM Temp (°C)', color='#E67E22', linewidth=2)
    axs[0].plot(df['time_hr'], df['t_boiler'], label='Boiler Temp (°C)', color='#2980B9', linewidth=2)
    axs[0].axhline(y=100, color='r', linestyle='--', alpha=0.5, label='Boiling Point')
    axs[0].set_ylabel('Temperature (°C)')
    axs[0].set_title('Thermal Stability: Battery vs Boiler')
    axs[0].legend()
    axs[0].grid(alpha=0.3)
    
    axs[1].plot(df['time_hr'], df['pcm_melt'], label=r'Melt Fraction ($\alpha$)', color='#8E44AD', linewidth=2)
    axs[1].fill_between(df['time_hr'], df['q_solar_kw']/df['q_solar_kw'].max(), alpha=0.2, color='#F1C40F', label='Solar Irradiance (Normalized)')
    axs[1].set_ylabel('Melt Fraction / Energy')
    axs[1].set_title('PCM Phase Storage Cycles')
    axs[1].legend()
    axs[1].grid(alpha=0.3)
    
    axs[2].plot(df['time_hr'], df['tds_ppm'], label='TDS Concentration (ppm)', color='#C0392B', linewidth=2)
    axs[2].set_ylabel('Salinity (ppm)')
    axs[2].set_title('Boiler Solids & Auto-Flush Triggers')
    axs[2].legend()
    axs[2].grid(alpha=0.3)
    
    axs[3].plot(df['time_hr'], df['total_distilled_L'], label='Cumulative Yield (L)', color='#27AE60', linewidth=3)
    axs[3].set_ylabel('Volume (Liters)')
    axs[3].set_xlabel('Mission Time (Hours)')
    axs[3].set_title('Continuous 24/7 Water Production')
    axs[3].legend()
    axs[3].grid(alpha=0.3)
    
    plt.tight_layout()
    plt.savefig("simulation_graphs.png", dpi=300)
    print("Graph saved as simulation_graphs.png")

if __name__ == "__main__":
    run_simulation()
