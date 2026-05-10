def get_binance_fee(vip_level=0, is_usdc=False, is_maker=False, using_bnb=False):
    """
    Returns the Binance trading fee as a decimal based on user tier and pair type.

    :param vip_level: int, 0 (Regular User) through 9
    :param is_usdc: bool, True if trading a USDC pair
    :param is_maker: bool, True for Maker order, False for Taker order
    :param using_bnb: bool, True if paying fees in BNB for the 25% discount
    :return: float, fee as a decimal (e.g. 0.001 for 0.1%)
    """

    # Table stores percentages: [Standard Maker, Standard Taker, USDC Taker]
    # Note: The table states USDC Maker is "Standard", meaning it shares the Standard Maker rate.
    fee_schedule = {
        0: {'std_maker': 0.100, 'std_taker': 0.100, 'usdc_taker': 0.095},
        1: {'std_maker': 0.090, 'std_taker': 0.100, 'usdc_taker': 0.095},
        2: {'std_maker': 0.080, 'std_taker': 0.100, 'usdc_taker': 0.095},
        3: {'std_maker': 0.040, 'std_taker': 0.060, 'usdc_taker': 0.055},
        4: {'std_maker': 0.040, 'std_taker': 0.052, 'usdc_taker': 0.047},
        5: {'std_maker': 0.025, 'std_taker': 0.031, 'usdc_taker': 0.026},
        6: {'std_maker': 0.020, 'std_taker': 0.029, 'usdc_taker': 0.024},
        7: {'std_maker': 0.019, 'std_taker': 0.028, 'usdc_taker': 0.023},
        8: {'std_maker': 0.016, 'std_taker': 0.025, 'usdc_taker': 0.020},
        9: {'std_maker': 0.011, 'std_taker': 0.023, 'usdc_taker': 0.018},
    }

    if vip_level not in fee_schedule:
        raise ValueError("VIP level must be an integer between 0 and 9.")

    rates = fee_schedule[vip_level]

    # Determine base percentage based on Maker vs Taker and USDC vs Standard
    if is_maker:
        base_fee_pct = rates['std_maker']
    else:
        base_fee_pct = rates['usdc_taker'] if is_usdc else rates['std_taker']

    # Apply the 25% BNB discount
    if using_bnb:
        base_fee_pct *= 0.75

    # Convert percentage to a usable decimal for math (e.g., 0.1% -> 0.001)
    return base_fee_pct / 100.0
