"""
AUTOBOT Metadata Engine - Static Metadata Management
Manages instrument trading rules and metadata from exchange
"""
import json
import logging
import os
from datetime import datetime
from typing import Dict, Optional, Any
from pathlib import Path

from core.notifier import notification_manager, NotificationPriority

logger = logging.getLogger("autobot.metadata")


class StaticMetadataEngine:
    """Manages static instrument metadata from exchange"""
    
    def __init__(self, metadata_dir: str = "/root/autobot_system/data/metadata"):
        self.metadata_dir = Path(metadata_dir)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        
        self._metadata: Dict[str, Dict] = {}
        self._load_latest_metadata()
    
    def _load_latest_metadata(self):
        """Load the latest metadata from disk"""
        
        latest_path = self.metadata_dir / "metadata_latest.json"
        
        if latest_path.exists():
            try:
                with open(latest_path, "r") as f:
                    self._metadata = json.load(f)
                logger.info(f"Loaded metadata for {len(self._metadata)} symbols")
            except Exception as e:
                logger.error(f"Failed to load metadata: {e}")
                notification_manager.send_error(
                    title="Metadata Load Failed",
                    message=str(e)
                )
        else:
            logger.warning("No metadata file found, system in COLD START state")
    
    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """Get metadata for a specific symbol"""
        
        return self._metadata.get(symbol)
    
    def get_tick_size(self, symbol: str) -> float:
        """Get tick size for price rounding"""
        
        info = self.get_symbol_info(symbol)
        if info and "order_rules" in info:
            price_filter = info["order_rules"].get("filters", {}).get("PRICE_FILTER", {})
            return float(price_filter.get("tickSize", 0.01))
        return 0.01
    
    def get_step_size(self, symbol: str) -> float:
        """Get step size for quantity rounding"""
        
        info = self.get_symbol_info(symbol)
        if info and "order_rules" in info:
            lot_size = info["order_rules"].get("filters", {}).get("LOT_SIZE", {})
            return float(lot_size.get("stepSize", 0.001))
        return 0.001
    
    def get_min_notional(self, symbol: str) -> float:
        """Get minimum notional value for orders"""
        
        info = self.get_symbol_info(symbol)
        if info and "order_rules" in info:
            min_notional = info["order_rules"].get("filters", {}).get("MIN_NOTIONAL", {})
            return float(min_notional.get("notional", 5.0))
        return 5.0
    
    def round_price(self, symbol: str, price: float) -> float:
        """Round price to exchange precision"""
        
        tick_size = self.get_tick_size(symbol)
        return round(price / tick_size) * tick_size
    
    def round_quantity(self, symbol: str, quantity: float) -> float:
        """Round quantity to exchange precision"""
        
        step_size = self.get_step_size(symbol)
        return round(quantity / step_size) * step_size
    
    def is_symbol_trading(self, symbol: str) -> bool:
        """Check if symbol is currently trading"""
        
        info = self.get_symbol_info(symbol)
        if info and "contract_specs" in info:
            return info["contract_specs"].get("status") == "TRADING"
        return False
    
    def get_all_symbols(self) -> list:
        """Get list of all available symbols"""
        
        return list(self._metadata.keys())
