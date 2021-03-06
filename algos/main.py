import torch
from torch import nn
from torch import optim
import torch.backends.cudnn as cudnn

import numpy as np
import pandas as pd
from tqdm import tqdm

import os
import time
import datetime
from opts import args

import data_preprocess
from nets import models
from nets import vcdnn
from nets import CNN_Text_Model
# from vcdnn import VDCNN
from helper import accuracy, AverageMeter, log_stats, LOG, plot_figs, confusion_matrix


def main(**kwargs):
    global args

    for arg, v in kwargs.items():
        args.__setattr__(arg, v)

    print(args)

    program_start_time = time.time()
    instanceName = "classification_Accuracy"
    folder_path = os.path.dirname(os.path.abspath(__file__))

    timestamp = datetime.datetime.now()
    ts_str = timestamp.strftime('%Y-%m-%d-%H-%M-%S')
    path = folder_path + os.sep + instanceName + os.sep + args.model + os.sep + ts_str+"_"+args.dataset+"_" + args.wordembedding

    if args.debug:
        print("[Debug mode]")
        path = folder_path + os.sep + instanceName + os.sep + "Debug-" + args.model + os.sep + ts_str+"_"+args.dataset+"_" + args.wordembedding
    else:
        path = folder_path + os.sep + instanceName + os.sep + args.model + os.sep + ts_str+"_"+args.dataset+"_" + args.wordembedding


    os.makedirs(path)
    
    args.savedir = path

    global logFile
    logFile = path + os.sep + "log.txt"

    if args.model == "BiLSTMConv":
        Model = models.BiLSTMConv
        

    # elif args.model == "BiGRU":
    #     Model = models.BiGRU

    # elif args.model == "WordCNN":
    #     Model = models.WordCNN

    # elif args.model == "BiGRUWithTimeDropout":
    #     Model = models.BiGRUWithTimeDropout

    elif args.model == "CNN_Text_Model":
        Model = CNN_Text_Model.CNN_Text
    elif args.model == "VDCNN":
        Model = vcdnn.VDCNN
    else:
        NotImplementedError

    # process the input data.
    
    captionStrDict = {
        "fig_title" : args.dataset,
        "x_label" : "epoch"
    }

    train_iter, test_iter, net = data_preprocess.prepare_data_and_model(Model=Model, args=args, using_gpu=True)
    print("args: ", args)

    LOG(str(args), logFile)

    global device
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    device = 'cuda'


    net = net.to(device)

    if device == 'cuda':
        net = torch.nn.DataParallel(net).cuda()
        cudnn.benchmark = True

    optimizer = optim.Adam(params=net.parameters(), lr=1e-3, weight_decay=1e-4)
    lr_scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=1000, gamma=.99)
    if device == "cuda":
        criterion = nn.CrossEntropyLoss().cuda()
    else:
        criterion = nn.CrossEntropyLoss()

    # criterion = nn.CrossEntropyLoss().cuda()

    best_test_acc = 0
    best_test_results = []
    ground_truth = []

    epoch_train_accs = []
    epoch_train_losses = []
    epoch_test_accs = []
    epoch_test_losses = []
    epoch_lrs = []

    for epoch in range(args.epochs):
        
        epoch_start_time = time.time()

        train_accs = []
        train_losses = []

        for batch in tqdm(train_iter):
            lr_scheduler.step()

            net.train()
            xs = batch.text
            ys = batch.label
            # # ys = ys.squeeze(1)
            # print("ys_train data type: ", type(ys))
            # print("ys_train: ", ys)
            if device == 'cuda':
                ys = ys.cuda(async=True)
            # ys = torch.autograd.Variable(ys)
            xs = torch.autograd.Variable(xs)
            ys_var = torch.autograd.Variable(ys)
            # print(ys_var)

            logits = net(xs)
            loss = criterion(logits, ys_var)
            # print("loss: ", loss.item())

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            train_losses.append(loss.item()/int(args.batch_size))
            train_accs.append(accuracy(logits.data, ys))

        train_accs_normal = [i[0].item() for i in train_accs]

        # print("epoch ", epoch, " :  training accumulated accuracy ", np.mean(train_accs_normal))
        LOG("epoch: "+ str(epoch), logFile)
        LOG("[TRAIN] accumulated accuracy: " + str(np.mean(train_accs_normal)), logFile)

        epoch_train_accs.append(np.mean(train_accs_normal))
        epoch_train_losses.append(np.mean(train_losses))

        

        test_accs = []
        test_losses = []
        test_predict_results = []

        best_test_acc = 0

        net.eval()

        
        pred_results = []
        
        print("running testing.....")
        for batch in tqdm(test_iter):
            xs_test = batch.text
            ys_test = batch.label


            logits_test = net(xs_test)
            test_loss = criterion(logits_test, ys_test)

            test_losses.append(test_loss.item() / int(args.batch_size))
            test_accs.append(accuracy(logits_test.data, ys_test))

            pred_results = pred_results + logits_test.topk(1, 1, True, True)[1].t().cpu().numpy().tolist()[0]
            
            if epoch == (args.epochs -1):
                ground_truth = ground_truth + ys_test.cpu().numpy().tolist()

        test_accs_normal = [i[0].item() for i in test_accs]

        # print("epoch {} :  testing accumulated accuracy {} %".format(epoch, np.mean(test_accs)))
        print("epoch ", epoch, " :  testing accumulated accuracy ", np.mean(test_accs_normal))

        # LOG("epoch: "+ str(epoch), logFile)
        LOG("[TEST] accumulated accuracy: " + str(np.mean(test_accs_normal)), logFile)
        
        if best_test_acc < np.mean(test_accs_normal):
            best_test_acc = np.mean(test_accs_normal)
            best_test_results = pred_results
            torch.save(net.state_dict(), path+os.sep+ str(Model.name)+".pkl")


        epoch_test_accs.append(np.mean(test_accs_normal))
        epoch_test_losses.append(np.mean(test_losses))
            
        

        # epoch_lrs.append(0.1)
        try:
            lr = float(str(optimizer[-1]).split("\n")[-5].split(" ")[-1])
        except:
            lr = 100
        epoch_lrs.append(lr)

        log_stats(path, [np.mean(train_accs_normal)], [np.mean(train_losses)], [np.mean(test_accs_normal)], [np.mean(test_losses)], lr)

        one_epoch_last_time = time.time() - epoch_start_time

        LOG("last time: " + str(one_epoch_last_time), logFile)

    df = pd.DataFrame(data={"test_label": best_test_results,
                            "ground truth": ground_truth})
    df.to_csv(path + os.sep + "test_classification_result.csv", sep=',', index=True)

    # save the metrics report
    logFile = confusion_matrix(df["test_label"], df["ground truth"], logFile)

# #     # here plot figures
# # algos\Classification_Accuracy\CNN_Text_Model\2019-01-23-14-58-01_tripadvisor\test_acc.txt
#     import pandas as pd
#     # algos\Classification_Accuracy\BiLSTMConv\\2019-01-22-10-29-54_tripadvisor\test_acc.txt
#     epoch_test_accs = list(pd.read_csv("algos\\Classification_Accuracy\\CNN_Text_Model\\2019-01-23-14-58-01_tripadvisor\\test_acc.txt", header=None).iloc[:,0])
#     epoch_train_accs = list(pd.read_csv("algos\\Classification_Accuracy\\CNN_Text_Model\\2019-01-23-14-58-01_tripadvisor\\train_acc.txt", header=None).iloc[:,0])
#     epoch_train_losses = list(pd.read_csv("algos\\Classification_Accuracy\\CNN_Text_Model\\2019-01-23-14-58-01_tripadvisor\\train_losses.txt", header=None).iloc[:,0])
#     epoch_test_losses = list(pd.read_csv("algos\\Classification_Accuracy\\CNN_Text_Model\\2019-01-23-14-58-01_tripadvisor\\test_losses.txt", header=None).iloc[:,0])


    plot_figs(epoch_train_accs, epoch_train_losses, epoch_test_accs, epoch_test_losses, args, captionStrDict)
    LOG("============Finish============", logFile)




if __name__ == '__main__':
    main()
    # epoch_train_accs = 
    # epoch_train_losses = 
    # epoch_test_accs = 
    # epoch_test_losses = 
    # args = 
    # captionStrDict = {
    #     "fig_title" : "test_dataset",
    #     "x_label" : "epoch"
    # }    

    # plot_figs(epoch_train_accs, epoch_train_losses, epoch_test_accs, epoch_test_losses, args, captionStrDict)
