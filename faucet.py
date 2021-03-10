from flask import (
    Flask,
    request,
)
from flask_stache import render_template
from flask_qrcode import QRcode
from bitcoin_rpc_class import RPCHost
import configparser
import json
import wallycore as wally

app = Flask(__name__, static_url_path='/static')
qrcode = QRcode(app)

config = configparser.RawConfigParser()
config.read('liquid.conf')

liquid_instance = config.get('GENERAL', 'liquid_instance')

rpcHost = config.get(liquid_instance, 'host')
rpcPort = config.get(liquid_instance, 'port')
rpcUser = config.get(liquid_instance, 'username')
rpcPassword = config.get(liquid_instance, 'password')
rpcPassphrase = config.get(liquid_instance, 'passphrase')
rpcWallet = config.get(liquid_instance, 'wallet')

if (len(rpcWallet) > 0):
    serverURL = 'http://' + rpcUser + ':' + rpcPassword + '@' + rpcHost + ':' + str(rpcPort) + '/wallet/' + rpcWallet
else:
    serverURL = 'http://' + rpcUser + ':' + rpcPassword + '@' + rpcHost + ':' + str(rpcPort)

host = RPCHost(serverURL)
if (len(rpcPassphrase) > 0):
    result = host.call('walletpassphrase', rpcPassphrase, 60)


@app.route('/', methods=['GET'])
def url_home():
    data = {}
    return render_template('home', **data)


def faucet(address, amount):
    if host.call('validateaddress', address)['isvalid']:
        tx = host.call('sendtoaddress', address, amount)
        data = "Sent "+str(amount)+" LBTC to address "+address+" with transaction "+tx+"."
    else:
        data = "Error"
    return data


@app.route('/faucet', methods=['GET'])
def url_faucet():
    balance = host.call('getbalance')['bitcoin']
    address = request.args.get('address')

    if address is None:
        data = {'result': 'missing address', 'balance': balance}
        data['form'] = True
        return render_template('faucet', **data)

    amount = 0.001
    data = {'result': faucet(address, amount), 'balance': balance}
    data['form'] = False
    return render_template('faucet', **data)


def issuer(asset_amount, asset_address, token_amount, token_address, issuer_pubkey, name, ticker, precision, domain):
    data = {}
    version = 0  # don't change
    blind = False
    feerate = 0.00003000

    asset_amount = int(asset_amount) / 10 ** (8 - int(precision))
    token_amount = int(token_amount) / 10 ** (8 - int(precision))

    # Create funded base tx
    base = host.call('createrawtransaction', [], [{'data': '00'}])
    funded = host.call('fundrawtransaction', base, {'feeRate': feerate})

    # Create the contact and calculate the asset id (Needed for asset registry!)
    contract = json.dumps({'name': name,
                           'ticker': ticker,
                           'precision': precision,
                           'entity': {'domain': domain},
                           'issuer_pubkey': issuer_pubkey,
                           'version': version}, separators=(',', ':'), sort_keys=True)
    contract_hash = wally.hex_from_bytes(wally.sha256(contract.encode('ascii')))
    data['contract'] = contract

    # Create the rawissuance transaction
    contract_hash_rev = wally.hex_from_bytes(wally.hex_to_bytes(contract_hash)[::-1])
    rawissue = host.call('rawissueasset', funded['hex'], [{'asset_amount': asset_amount,
                                                           'asset_address': asset_address,
                                                           'token_amount': token_amount,
                                                           'token_address': token_address,
                                                           'blind': blind,
                                                           'contract_hash': contract_hash_rev}])

    # Blind the transaction
    blind = host.call('blindrawtransaction', rawissue[0]['hex'], True, [], False)

    # Sign transaction
    signed = host.call('signrawtransactionwithwallet', blind)
    decoded = host.call('decoderawtransaction', signed['hex'])
    data['asset_id'] = decoded['vin'][0]['issuance']['asset']

    # Test transaction
    test = host.call('testmempoolaccept', [signed['hex']])
    if test[0]['allowed'] is True:
        txid = host.call('sendrawtransaction', signed['hex'])
        data['txid'] = txid
        data['registry'] = {'asset_id': data['asset_id'],
                            'contract': json.loads(data['contract'])}

    return data


@app.route('/issuer', methods=['GET'])
def url_issuer():
    command = request.args.get('command')
    if command == 'asset':
        asset_amount = int(request.args.get('asset_amount'))
        asset_address = request.args.get('asset_address')
        token_amount = int(request.args.get('token_amount'))
        token_address = request.args.get('token_address')
        issuer_pubkey = request.args.get('pubkey')
        name = request.args.get('name')
        ticker = request.args.get('ticker')
        precision = request.args.get('precision')
        domain = request.args.get('domain')
        data = issuer(asset_amount, asset_address, token_amount, token_address, issuer_pubkey, name, ticker, precision, domain)
        data['form'] = False
        data['domain'] = domain
    else:
        data = {}
        data['form'] = True
    return render_template('issuer', **data)


def opreturn(text):
    base = host.call('createrawtransaction', [], [{'data': text}])
    funded = host.call('fundrawtransaction', base)
    blind = host.call('blindrawtransaction', funded['hex'], True, [], False)
    signed = host.call('signrawtransactionwithwallet', blind)
    test = host.call('testmempoolaccept', [signed['hex']])
    if test[0]['allowed'] is True:
        return host.call('sendrawtransaction', signed['hex'])
    return


def test(tx):
    return host.call('testmempoolaccept', [tx])


def broadcast(tx):
    test = host.call('testmempoolaccept', [tx])
    if test[0]['allowed'] is True:
        return host.call('sendrawtransaction', tx)
    return


@app.route('/utils', methods=['GET'])
def url_utils():
    command = request.args.get('command')
    if command == 'opreturn':
        text = request.args.get('text')
        data = {'result_opreturn': opreturn(text)}
        data['form_opreturn'] = False
        data['form_test'] = True
        data['form_broadcast'] = True

    elif command == 'test':
        tx = request.args.get('tx')
        data = {'result_test': test(tx)}
        data['form_opreturn'] = True
        data['form_test'] = False
        data['form_broadcast'] = True

    elif command == 'broadcast':
        tx = request.args.get('tx')
        data = {'result_broadcast': broadcast(tx)}
        data['form_opreturn'] = True
        data['form_test'] = True
        data['form_broadcast'] = False

    else:
        data = {}
        data['form_opreturn'] = True
        data['form_test'] = True
        data['form_broadcast'] = True

    return render_template('utils', **data)


if __name__ == '__main__':
    app.import_name = '.'
    app.run(host='0.0.0.0', port=80)
