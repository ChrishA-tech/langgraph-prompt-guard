import os

# Tests are deterministic: the API never loads whichever trained model happens to be committed in models/.
os.environ["PROMPTGUARD_CLASSIFIER"] = "off"
