# Fit checker (c2)
`from data.fit_checker import check_fit`; `from data.fit_checker.normalize import from_dataset`.
Pure functions. A missing attr = unknown = `uncertain` for that check. Overall: any fail -> fail, else any uncertain -> uncertain, else pass.

Rules: `fit.cpu_socket` (with LGA1151 generation and BIOS notes), `fit.ram_type`, `fit.ram_slots`, `fit.psu_wattage`
(max of maker's recommended PSU and est. load x 1.25), `fit.gpu_connectors`, `fit.gpu_length`, `fit.cooler_socket`,
`fit.cooler_height` (radiator mounts for AIOs), `fit.form_factor`, `fit.psu_form_factor`, `fit.storage`.

attrs per SpecCard category:
- cpu: socket, microarchitecture, tdp_w, vendor (AMD|Intel), max_power_w?
- motherboard: socket, chipset, chipset_series, form_factor (ATX|Micro ATX|Mini ITX|EATX), memory_type, memory_slots, memory_max_speed_mhz?, m2_slots, sata_ports
- memory: type (DDR4|DDR5), speed_mhz, modules, module_gb
- gpu: chipset (e.g. "RTX 5070 Ti"), length_mm, board_power_w?, rec_psu_w?, power_connector? (["16pin", min 8-pin for adapter] or ["8pin", n])
- psu: wattage, form_factor (ATX|SFX|SFX-L), pcie_16pin, pcie_8pin
- case: type, motherboard_form_factors, max_gpu_length_mm, max_cooler_height_mm, psu_form_factors, radiator_mounts_mm?
- cooler: type (air|aio), height_mm, radiator_mm, sockets
- storage: interface (as in dataset, e.g. "M.2 PCIe 4.0 X4", "SATA 6.0 Gb/s"), form_factor

Hand tables (`tables.py`): CPU microarchitecture to socket, GPU chipset to board power / recommended PSU / connector,
BIOS notes, case type to board and PSU form factors.
The dataset has no case clearances, cooler heights or PSU connector counts; those come from listings (Apify) or are uncertain.
