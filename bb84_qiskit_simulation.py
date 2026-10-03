"""
BB84 Quantum Key Distribution (QKD) & Post-Processing Pipeline
Author / Institution: Rensselaer Polytechnic Institute (RPI) & IBM Quantum Hackathon Reference
Compatible with Qiskit 1.0+ and Qiskit Aer
"""

import numpy as np
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
from qiskit_aer import AerSimulator

def binary_entropy(p: float) -> float:
    """Calculates binary Shannon entropy H2(p)."""
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return -p * np.log2(p) - (1.0 - p) * np.log2(1.0 - p)

def run_bb84_simulation(
    num_qubits: int = 100,
    eve_strategy: str = "intercept_resend",  # "none", "intercept_resend", "cnot_probe"
    channel_depolarizing_error: float = 0.02,
    sample_fraction: float = 0.25,
    seed: int = 42
):
    np.random.seed(seed)
    backend = AerSimulator()

    # Step 1: Alice state preparation
    alice_bits = np.random.randint(0, 2, size=num_qubits)
    alice_bases = np.random.choice(['Z', 'X'], size=num_qubits)

    # Bob's independent measurement bases
    bob_bases = np.random.choice(['Z', 'X'], size=num_qubits)

    # Eve's setup
    eve_bases = np.random.choice(['Z', 'X'], size=num_qubits)
    eve_bits = []

    bob_bits = []

    # Simulate transmission qubit by qubit using Qiskit circuits
    for i in range(num_qubits):
        qr = QuantumRegister(2, 'q')  # q[0]: transmission qubit, q[1]: Eve ancilla probe
        cr = ClassicalRegister(2, 'c')
        qc = QuantumCircuit(qr, cr)

        # Alice encodes bit
        if alice_bits[i] == 1:
            qc.x(qr[0])
        # Alice encodes basis
        if alice_bases[i] == 'X':
            qc.h(qr[0])

        # Eavesdropping attacks
        if eve_strategy == "intercept_resend":
            # Eve measures in random basis
            if eve_bases[i] == 'X':
                qc.h(qr[0])
            qc.measure(qr[0], cr[1])
            # Re-prepare state based on Eve's measurement
            if eve_bases[i] == 'X':
                qc.h(qr[0])

        elif eve_strategy == "cnot_probe":
            # Eve entangles an ancilla probe qubit via CNOT
            qc.cx(qr[0], qr[1])
            qc.measure(qr[1], cr[1])

        # Realistic channel depolarizing / phase-flip noise
        if np.random.rand() < channel_depolarizing_error:
            qc.x(qr[0])  # Bit-flip component

        # Bob's measurement
        if bob_bases[i] == 'X':
            qc.h(qr[0])
        qc.measure(qr[0], cr[0])

        # Execute single shot
        job = backend.run(qc, shots=1, memory=True)
        result = job.result()
        measured_str = result.get_memory()[0]  # format: "cr[1] cr[0]"
        parts = measured_str.split()
        if len(parts) == 1:
            # Depending on Qiskit formatting, 2 bits concatenated
            b_bob = int(measured_str[-1])
            b_eve = int(measured_str[0]) if len(measured_str) > 1 else 0
        else:
            b_bob = int(parts[0])
            b_eve = int(parts[1]) if len(parts) > 1 else 0

        bob_bits.append(b_bob)
        eve_bits.append(b_eve)

    bob_bits = np.array(bob_bits)
    eve_bits = np.array(eve_bits)

    # Step 2: Sifting (basis reconciliation)
    matching_indices = np.where(alice_bases == bob_bases)[0]
    sifted_alice = alice_bits[matching_indices]
    sifted_bob = bob_bits[matching_indices]
    sifted_len = len(sifted_alice)

    # Step 3: Parameter Estimation (QBER)
    sample_size = int(sifted_len * sample_fraction)
    if sample_size < 1:
        sample_size = 1

    sample_idx = np.random.choice(sifted_len, size=sample_size, replace=False)
    comp_alice = sifted_alice[sample_idx]
    comp_bob = sifted_bob[sample_idx]

    num_errors = np.sum(comp_alice != comp_bob)
    qber = num_errors / sample_size

    # Shor-Preskill security threshold check (11%)
    shor_preskill_abort_threshold = 0.11
    is_aborted = qber > shor_preskill_abort_threshold

    # Remaining key for error correction and privacy amplification
    remaining_mask = np.ones(sifted_len, dtype=bool)
    remaining_mask[sample_idx] = False
    reconciled_alice = sifted_alice[remaining_mask]
    reconciled_bob = sifted_bob[remaining_mask]

    # Step 4: Theoretical Asymptotic Key Rate & Information Leakage
    h2_qber = binary_entropy(qber)
    leak_ec = 1.16 * h2_qber  # Cascade protocol leakage overhead
    key_rate_R = max(0.0, 1.0 - 2.0 * h2_qber)
    
    # Mutual information
    i_ab = 1.0 - h2_qber
    if eve_strategy == "none":
        i_ae = 0.0
    elif eve_strategy == "intercept_resend":
        i_ae = 0.5  # Eve gets 50% info due to basis matching
    else:
        i_ae = 0.35  # Partial information from CNOT probe
    delta_i = i_ab - i_ae

    # Step 5: Privacy Amplification (Toeplitz Hashing Simulation)
    final_key_len = int(len(reconciled_alice) * key_rate_R) if not is_aborted else 0
    final_secret_key = []

    if final_key_len > 0 and len(reconciled_alice) > 0:
        n = len(reconciled_alice)
        m = final_key_len
        # Construct random Toeplitz matrix T of size m x n
        toeplitz_seed = np.random.randint(0, 2, size=n + m - 1)
        # Multiplication over GF(2)
        T = np.zeros((m, n), dtype=int)
        for r in range(m):
            T[r] = toeplitz_seed[m - 1 - r : m - 1 - r + n]
        final_secret_key = np.dot(T, reconciled_alice) % 2

    return {
        "num_qubits": num_qubits,
        "sifted_length": sifted_len,
        "sample_size": sample_size,
        "qber": float(qber),
        "qber_percent": float(qber * 100),
        "is_aborted": bool(is_aborted),
        "asymptotic_key_rate_R": float(key_rate_R),
        "mutual_information_I_AB": float(i_ab),
        "mutual_information_I_AE": float(i_ae),
        "delta_I": float(delta_i),
        "final_secret_key_length": int(final_key_len),
        "final_secret_key": "".join(map(str, final_secret_key)) if len(final_secret_key) > 0 else "ABORTED"
    }

if __name__ == "__main__":
    print("=================================================================")
    print("   RPI & IBM Quantum: BB84 QKD End-to-End Simulation Pipeline    ")
    print("=================================================================\n")

    # Run without Eve
    res_no_eve = run_bb84_simulation(num_qubits=200, eve_strategy="none")
    print(f"[No Eve] QBER: {res_no_eve['qber_percent']:.2f}% | Aborted: {res_no_eve['is_aborted']} | Key Rate R: {res_no_eve['asymptotic_key_rate_R']:.3f} | Final Key: {res_no_eve['final_secret_key_length']} bits")

    # Run with Intercept-Resend Eve
    res_eve = run_bb84_simulation(num_qubits=200, eve_strategy="intercept_resend")
    print(f"[Eve Intercept-Resend] QBER: {res_eve['qber_percent']:.2f}% | Aborted: {res_eve['is_aborted']} | Delta I: {res_eve['delta_I']:.3f}")
