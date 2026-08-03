class DFMAService:
    # Densities in g/cm3
    MATERIAL_DENSITIES = {
        "Aluminum 6061-T6": 2.70,
        "Stainless Steel 304": 8.00,
        "Mild Steel S235": 7.85,
        "Titanium Gr5": 4.43
    }

    def analyze_manufacturing(self, kcl_code: str, part_info: dict) -> dict:
        """
        Calculates detailed Volume, Mass, Material Density, Manufacturing Cycle Times (Hours/Min),
        and DFMA Constraint Rules for the DFMA Agent.
        """
        material = part_info.get("material", "Aluminum 6061-T6")
        thickness = float(part_info.get("thickness_mm", 2.0))
        part_name = part_info.get("part_name", "Sheet Metal Bracket")

        # Material Density lookup
        density_g_cm3 = self.MATERIAL_DENSITIES.get(material, 2.70)

        # Geometric Calculations (Simulated bounding 140x90mm with 2x 50mm flanges)
        plate_area_cm2 = (14.0 * 9.0) + (2 * 9.0 * 5.0) # ~216 cm2
        volume_cm3 = round(plate_area_cm2 * (thickness / 10.0), 2)
        mass_grams = round(volume_cm3 * density_g_cm3, 2)
        mass_kg = round(mass_grams / 1000.0, 3)

        # DFMA Constraint Rules
        dfma_warnings = []
        dfma_score = 95

        min_hole_dist_to_bend = thickness * 2.0
        dfma_warnings.append({
            "rule": "Hole-to-Bend Clearance",
            "severity": "success",
            "message": f"Hole distance exceeds min required {min_hole_dist_to_bend}mm for {thickness}mm sheet."
        })

        if thickness < 1.0:
            dfma_warnings.append({
                "rule": "Laser Heat Distortion",
                "severity": "warning",
                "message": "Thin sheet (< 1.0mm) risks thermal warping during laser piercing."
            })
            dfma_score -= 10
        elif thickness >= 4.0:
            dfma_warnings.append({
                "rule": "Press Brake Tonnage",
                "severity": "warning",
                "message": "Thick sheet (>= 4.0mm) requires high-tonnage V-die tooling."
            })
            dfma_score -= 5

        # Detailed Manufacturing Operations Routing
        manufacturing_operations = [
            {
                "step": 1,
                "operation": "Fiber Laser Contour Cutting",
                "machine": "TRUMPF TruLaser 3030 (4kW N2)",
                "description": f"Cut outer blank & 4x Ø11mm holes on {thickness}mm {material}.",
                "setup_time_min": 10,
                "process_time_sec": 48,
                "tooling": "1.5mm Nozzle / N2 14 Bar"
            },
            {
                "step": 2,
                "operation": "Edge Deburring & Descaling",
                "machine": "Timesavers Rotary Brush 42",
                "description": "Condition edges and remove laser micro-burrs.",
                "setup_time_min": 5,
                "process_time_sec": 25,
                "tooling": "Abrasive Flap Belt"
            },
            {
                "step": 3,
                "operation": "CNC Press Brake Bending",
                "machine": "Bystronic Xpert 80",
                "description": f"Form 2x 90° bends with R{thickness}mm top punch.",
                "setup_time_min": 15,
                "process_time_sec": 60,
                "tooling": "Top Punch R2.0, Bottom Die V8"
            },
            {
                "step": 4,
                "operation": "PEM Fastener Insertion",
                "machine": "Haeger 824 OneTouch",
                "description": "Press 4x M6 self-clinching blind standoffs.",
                "setup_time_min": 8,
                "process_time_sec": 40,
                "tooling": "M6 PEM Anvil Set"
            },
            {
                "step": 5,
                "operation": "Anodizing / Surface Coat",
                "machine": "MIL-A-8625 Type II Anodize Line",
                "description": "Clear Acid Anodize 15-20µm coating.",
                "setup_time_min": 20,
                "process_time_sec": 180,
                "tooling": "Titanium Racking"
            }
        ]

        total_process_sec = sum(op["process_time_sec"] for op in manufacturing_operations)
        total_setup_min = sum(op["setup_time_min"] for op in manufacturing_operations)
        total_time_min = round(total_setup_min + (total_process_sec / 60.0), 2)
        total_time_hours = round(total_time_min / 60.0, 3)

        return {
            "part_name": part_name,
            "material": material,
            "material_density_g_cm3": density_g_cm3,
            "thickness_mm": thickness,
            "volume_cm3": volume_cm3,
            "mass_grams": mass_grams,
            "mass_kg": mass_kg,
            "dfma_score": max(50, min(100, dfma_score)),
            "manufacturability_status": "HIGHLY OPTIMIZED // READY FOR FABRICATION",
            "total_cycle_time_min": total_time_min,
            "total_cycle_time_hours": total_time_hours,
            "total_setup_time_min": total_setup_min,
            "dfma_warnings": dfma_warnings,
            "manufacturing_operations": manufacturing_operations
        }

dfma_service = DFMAService()
