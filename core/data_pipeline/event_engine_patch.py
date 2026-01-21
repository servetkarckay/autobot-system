# _execute_signal metodu için position sizing entegrasyonu

# ESKİ:
async def _execute_signal(self, signal: TradeSignal, price: float, quantity: float):
    result = self.order_manager.submit_order(signal, quantity=quantity, price=price)

# YENİ:
async def _execute_signal(self, signal: TradeSignal, price: float, quantity: float = None):
    # Position sizing hesapla
    if quantity is None:
        pos_result = position_sizer.calculate_from_signal(
            equity=self._state.equity,
            signal=signal,
            current_price=signal.suggested_price if signal.suggested_price > 0 else price
        )
        if not pos_result.valid:
            logger.warning(f"Position sizing failed: {pos_result.reason}")
            return
        quantity = pos_result.quantity
    
    # Order submit
    result = self.order_manager.submit_order(signal, quantity, price)
