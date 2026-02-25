"""
Secure storage for sensitive data (API keys, passwords)
Uses system keyring when available, falls back to encrypted QSettings
"""
import base64
import hashlib
import os
from qgis.PyQt.QtCore import QSettings


class SecureStorage:
    """Manage secure storage of credentials using system keyring or encryption"""
    
    SERVICE_NAME = "KADAS_Altair_Plugin"
    
    def __init__(self):
        self.settings = QSettings()
        self._keyring_available = self._check_keyring()
        
        # Generate encryption key from machine-specific data
        self._encryption_key = self._get_encryption_key()
    
    def _check_keyring(self):
        """Check if keyring is available"""
        try:
            import keyring
            # Test if keyring backend is available
            keyring.get_keyring()
            return True
        except Exception:
            return False
    
    def _get_encryption_key(self):
        """Generate encryption key from machine-specific data"""
        try:
            from cryptography.fernet import Fernet
            
            # Use machine ID or create one
            machine_id = self.settings.value("AltairEOData/machine_id", "")
            if not machine_id:
                # Generate and store a unique machine ID
                machine_id = base64.urlsafe_b64encode(os.urandom(32)).decode()
                self.settings.setValue("AltairEOData/machine_id", machine_id)
                self.settings.sync()
            
            # Create Fernet key from machine ID
            key = hashlib.sha256(machine_id.encode()).digest()
            key_b64 = base64.urlsafe_b64encode(key)
            return Fernet(key_b64)
        except ImportError:
            # Cryptography not available
            return None
    
    def store_credential(self, service, username, password):
        """
        Store credential securely
        
        Args:
            service: Service name (e.g., 'oneatlas', 'planet', 'copernicus')
            username: Username or API key name
            password: Password or API key value
        """
        if self._keyring_available:
            self._store_in_keyring(service, username, password)
        elif self._encryption_key:
            self._store_encrypted(service, username, password)
        else:
            # Fallback: store obfuscated (not secure, but better than plaintext)
            self._store_obfuscated(service, username, password)
    
    def retrieve_credential(self, service, username):
        """
        Retrieve credential securely
        
        Args:
            service: Service name
            username: Username or API key name
            
        Returns:
            Password or API key value, or empty string if not found
        """
        if self._keyring_available:
            return self._retrieve_from_keyring(service, username)
        elif self._encryption_key:
            return self._retrieve_encrypted(service, username)
        else:
            return self._retrieve_obfuscated(service, username)
    
    def delete_credential(self, service, username):
        """Delete stored credential"""
        if self._keyring_available:
            try:
                import keyring
                keyring.delete_password(self.SERVICE_NAME, f"{service}:{username}")
            except Exception:
                pass
        
        # Also remove from QSettings
        key = f"AltairEOData/credentials/{service}/{username}"
        self.settings.remove(key)
        self.settings.sync()
    
    def _store_in_keyring(self, service, username, password):
        """Store in system keyring"""
        try:
            import keyring
            keyring.set_password(self.SERVICE_NAME, f"{service}:{username}", password)
        except Exception as e:
            # Fallback to encrypted storage
            if self._encryption_key:
                self._store_encrypted(service, username, password)
    
    def _retrieve_from_keyring(self, service, username):
        """Retrieve from system keyring"""
        try:
            import keyring
            password = keyring.get_password(self.SERVICE_NAME, f"{service}:{username}")
            return password or ""
        except Exception:
            # Fallback to encrypted storage
            if self._encryption_key:
                return self._retrieve_encrypted(service, username)
            return ""
    
    def _store_encrypted(self, service, username, password):
        """Store with encryption"""
        try:
            encrypted = self._encryption_key.encrypt(password.encode())
            encrypted_b64 = base64.b64encode(encrypted).decode()
            
            key = f"AltairEOData/credentials/{service}/{username}"
            self.settings.setValue(key, encrypted_b64)
            self.settings.sync()
        except Exception:
            # Fallback to obfuscated
            self._store_obfuscated(service, username, password)
    
    def _retrieve_encrypted(self, service, username):
        """Retrieve encrypted credential"""
        try:
            key = f"AltairEOData/credentials/{service}/{username}"
            encrypted_b64 = self.settings.value(key, "")
            
            if not encrypted_b64:
                return ""
            
            encrypted = base64.b64decode(encrypted_b64.encode())
            decrypted = self._encryption_key.decrypt(encrypted)
            return decrypted.decode()
        except Exception:
            # Try obfuscated fallback
            return self._retrieve_obfuscated(service, username)
    
    def _store_obfuscated(self, service, username, password):
        """Store obfuscated (base64, not secure but better than plaintext)"""
        obfuscated = base64.b64encode(password.encode()).decode()
        key = f"AltairEOData/credentials_obf/{service}/{username}"
        self.settings.setValue(key, obfuscated)
        self.settings.sync()
    
    def _retrieve_obfuscated(self, service, username):
        """Retrieve obfuscated credential"""
        try:
            key = f"AltairEOData/credentials_obf/{service}/{username}"
            obfuscated = self.settings.value(key, "")
            
            if not obfuscated:
                return ""
            
            return base64.b64decode(obfuscated.encode()).decode()
        except Exception:
            return ""
    
    def get_storage_method(self):
        """Get current storage method for display"""
        if self._keyring_available:
            return "System Keyring (Secure)"
        elif self._encryption_key:
            return "Encrypted (Secure)"
        else:
            return "Obfuscated (Warning: Not fully secure)"
    
    def store_credentials(self, service, credentials_dict):
        """
        Store multiple credentials as a dictionary
        
        Args:
            service: Service name (e.g., 'oneatlas', 'planet')
            credentials_dict: Dictionary of credential key-value pairs
        """
        for key, value in credentials_dict.items():
            if value:  # Only store non-empty values
                self.store_credential(service, key, value)
    
    def get_credentials(self, service):
        """
        Retrieve all credentials for a service as a dictionary
        
        Args:
            service: Service name (e.g., 'oneatlas', 'planet', 'copernicus')
            
        Returns:
            Dictionary of stored credentials, or None if not found
        """
        # Try to find all stored credentials for this service
        credentials = {}
        
        # Check common credential keys based on service
        if service == 'oneatlas':
            client_id = self.retrieve_credential(service, 'client_id')
            client_secret = self.retrieve_credential(service, 'client_secret')
            if client_id or client_secret:
                credentials['client_id'] = client_id
                credentials['client_secret'] = client_secret
        elif service == 'copernicus':
            # Copernicus uses OAuth2 client credentials (same as OneAtlas)
            client_id = self.retrieve_credential(service, 'client_id')
            client_secret = self.retrieve_credential(service, 'client_secret')
            if client_id or client_secret:
                credentials['client_id'] = client_id
                credentials['client_secret'] = client_secret
        elif service == 'planet':
            api_key = self.retrieve_credential(service, 'api_key')
            if api_key:
                credentials['api_key'] = api_key
        
        return credentials if credentials else None


# Global instance
_secure_storage = None

def get_secure_storage():
    """Get global SecureStorage instance"""
    global _secure_storage
    if _secure_storage is None:
        _secure_storage = SecureStorage()
    return _secure_storage
