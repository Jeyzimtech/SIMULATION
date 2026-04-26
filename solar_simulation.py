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

class MineralCartridgeModule:
    """Post-distillation mineral addition."""
    def __init__(self, target_concentration=50.0): # ppm of Ca/Mg
        self.target_concentration = target_concentration
        self.minerals_added_total = 0.0

    def step(self, distilled_mass):
        # Adds minerals to the distilled water
        added_mass = distilled_mass * (self.target_concentration / 1e6)
        self.minerals_added_total += added_mass
        return self.target_concentration

class SolarBatteryModule:
    """Electrical storage for pumps and sensors."""
    def __init__(self, capacity_wh=1000):
        self.capacity_j = capacity_wh * 3600
        self.charge_j = self.capacity_j * 0.8 # Start at 80%
        self.efficiency = 0.95

    def step(self, power_in, power_out, dt):
        net_energy = (power_in * self.efficiency - power_out) * dt
        self.charge_j = max(0, min(self.capacity_j, self.charge_j + net_energy))
        return (self.charge_j / self.capacity_j) * 100

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
    """Solar Concentrator with Sun Tracking."""
    def __init__(self, area=1.8, efficiency=0.75):
        self.area = area
        self.efficiency = efficiency
        self.is_tracking = True # Parabolic mirror follows the sun

    def step(self, time_of_day_hours, cloud_factor=1.0):
        # Time 0 is midnight. Sunrise at 6, Sunset at 18
        if 6.5 <= time_of_day_hours <= 17.5:
            # Tracking mirror maintains maximum irradiance normal to the surface
            dni = 950 # Near-peak DNI during the day due to tracking
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
        self.water_mass = 2.0 # initial kg (reduced to speed up startup)
        self.t_water = 25.0
        self.tds_ppm = 1000.0 # Initial salinity
        self.cp_water = 4184
        self.h_vap = 2260000
    
    def get_heat_transfer(self, t_pcm, U_coeff=250.0):
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

    def execute(self, boiler_level, steam_temp, boiler_tds, battery_soc, time_min):
        # Level control - only pump if battery has energy
        if boiler_level < 5.0 and battery_soc > 5: # Higher minimum for stability
            self.pump_on = True
            self.inlet_valve_open = True
        elif boiler_level > 20.0 or battery_soc <= 1: # Increased upper limit
            self.pump_on = False
            self.inlet_valve_open = False
            
        # Venting Logic (Requirement: 2-5 mins every hour before boiling/continuously)
        # We trigger the VENT path if either temp is low OR during the periodic window
        window_min = time_min % 60
        is_vent_window = (2 <= window_min <= 5)
        
        if steam_temp < 100.0 or is_vent_window:
            self.fractional_valve_dest = "VENT"
        else:
            self.fractional_valve_dest = "CONDENSER"
            
        # Flushing logic (simulating sludge drain)
        if boiler_tds > 10000.0: # 10,000 ppm limit
            self.drain_valve_open = True
            if battery_soc > 5: self.pump_on = True # Flush with fresh water
        else:
            self.drain_valve_open = False

def run_simulation(days=3):
    print("Initializing Solar-Thermal Distillation Simulation...")
    # Area tuned to hit the middle of the 50-80L range (~70L)
    csp = CSPModule(area=11.0, efficiency=0.85) 
    # Optimized PCM storage to balance startup time and night-time boiling
    pcm = ParrafinBatteryModule(mass=350) 
    boiler = BoilerModule()
    heat_recv = HeatRecoveryModule()
    controller = SupervisoryController()
    mineral = MineralCartridgeModule()
    battery = SolarBatteryModule(capacity_wh=5000) # Larger battery for higher throughput
    
    dt = 60 # 1 minute steps
    total_steps = int((days * 24 * 3600) / dt)
    feed_flow_rate = 0.05 # kg/s - slower feed to reduce thermal shock
    ambient_temp = 25.0
    
    total_distilled = 0.0
    history = []
    feed_temp_preheated = ambient_temp
    
    for step in range(total_steps):
        time_seconds = step * dt
        time_hours = (time_seconds / 3600) % 24
        total_time_hr = time_seconds / 3600.0
        
        # 1. Solar Battery Step (PV simulation)
        p_pv = 0
        if 6 <= time_hours <= 18:
            p_pv = 600 * math.sin(math.pi * (time_hours - 6) / 12) * 0.5 * 0.2 * 1000 # Simplified PV watts
            p_pv = max(0, p_pv / 1000) # kW scale
        
        p_pump = 0.2 if controller.pump_on else 0.05 # kW for pump vs electronics
        battery_soc = battery.step(p_pv, p_pump, dt)
        
        power_source = "BATTERY"
        if p_pv > p_pump:
            power_source = "SOLAR"
        elif p_pv > 0:
            power_source = "HYBRID"

        # 2. Controller Execute
        time_min = time_seconds / 60.0
        controller.execute(
            boiler_level=boiler.water_mass,
            steam_temp=boiler.t_water,
            boiler_tds=boiler.tds_ppm,
            battery_soc=battery_soc,
            time_min=time_min
        )
        
        # Actions applied
        if controller.drain_valve_open:
            boiler.water_mass = max(0.1, boiler.water_mass - 0.5 * dt)
            
        m_dot_feed = feed_flow_rate if controller.pump_on and controller.inlet_valve_open else 0.0
        feed_mass = m_dot_feed * dt
        
        # 3. Thermal Environment
        q_solar = csp.step(time_hours)
        q_to_boiler = boiler.get_heat_transfer(pcm.t_pcm)
        
        pcm.step(q_in=q_solar, q_out=q_to_boiler, dt=dt)
        # Use preheated water if available
        m_dot_steam, t_steam = boiler.step(feed_mass, feed_temp_preheated, q_to_boiler, dt)
        
        # 4. Heat Recovery / Conversion
        mineral_ppm = 0.0
        if controller.fractional_valve_dest == "CONDENSER" and m_dot_steam > 0:
            # All steam is condensed, but recovery preheats the NEXT feed step
            t_pre, _ = heat_recv.step(max(0.01, m_dot_feed), ambient_temp, m_dot_steam, t_steam, dt)
            feed_temp_preheated = t_pre
            
            distilled_step = m_dot_steam * dt
            total_distilled += distilled_step
            mineral_ppm = mineral.step(distilled_step)
        else:
            feed_temp_preheated = ambient_temp
            
        history.append({
            "time_hr": total_time_hr,
            "q_solar_kw": q_solar / 1000.0,
            "t_pcm": pcm.t_pcm,
            "pcm_melt": pcm.melt_fraction,
            "t_boiler": boiler.t_water,
            "boiler_vol": boiler.water_mass,
            "tds_ppm": boiler.tds_ppm,
            "total_distilled_L": total_distilled,
            "battery_soc": battery_soc,
            "mineral_ppm": mineral_ppm,
            "power_source": power_source
        })

    # Save to CSV
    csv_file = "simulation_results.csv"
    with open(csv_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=history[0].keys())
        writer.writeheader()
        writer.writerows(history)
        
    avg_per_24 = total_distilled / days
    print(f"Simulation completed! Total Distilled Water over {days} day(s): {total_distilled:.2f} Liters")
    print(f"Average Production: {avg_per_24:.2f} L / 24hrs (Target: 50-80L)")
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
    
    axs[1].plot(df['time_hr'], df['battery_soc'], label='Solar Battery SoC (%)', color='#27AE60', linewidth=2)
    axs[1].fill_between(df['time_hr'], df['q_solar_kw']/df['q_solar_kw'].max() if df['q_solar_kw'].max()>0 else 0, alpha=0.2, color='#F1C40F', label='Tracking Solar Heat (kW)')
    axs[1].set_ylabel('Battery % / Heat')
    axs[1].set_title('Electrical Storage & Tracking Solar Input')
    axs[1].legend()
    axs[1].grid(alpha=0.3)
    
    axs[2].plot(df['time_hr'], df['tds_ppm'], label='TDS Concentration (ppm)', color='#C0392B', linewidth=2)
    axs[2].set_ylabel('Salinity (ppm)')
    axs[2].set_title('Boiler Solids & Auto-Flush Triggers')
    axs[2].legend()
    axs[2].grid(alpha=0.3)
    
    axs[3].plot(df['time_hr'], df['total_distilled_L'], label='Cumulative Yield (L)', color='#27AE60', linewidth=3)
    days_sim = df['time_hr'].max() / 24
    # Requirement: 50L min, 80L max. We show the 80L target slope.
    target_line = [ (h/24)*80 for h in df['time_hr'] ]
    axs[3].plot(df['time_hr'], target_line, '--', color='#16A085', alpha=0.6, label='Target (80L/Day)')
    axs[3].set_ylabel('Volume (Liters)')
    axs[3].set_xlabel('Mission Time (Hours)')
    axs[3].set_title(f'Continuous Production: {df["total_distilled_L"].max()/days_sim:.1f}L/24hr Avg')
    axs[3].legend()
    axs[3].grid(alpha=0.3)
    
    plt.tight_layout()
    plt.savefig("simulation_graphs.png", dpi=300)
    print("Graph saved as simulation_graphs.png")

if __name__ == "__main__":
    run_simulation(days=1)
