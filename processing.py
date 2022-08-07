# -*- coding: utf-8 -*-
"""
Created on Tue Apr 20 15:11:43 2021
@author: Xinyi
"""

import pandas as pd
import math
import re
import numpy as np

import psycopg2


cidName = "dbscanid_50_4"
clusterName = "DBSCAN_50_4"
tweetTable = "staypoints_wi_il_dist65_nomerge"
zoneTable = "activityzone_dist65_nomerge"
referTable = "locations"
activityzone_file = "activityNodes.csv"

# Each node represents an individual stay point
activityNodes = []
tweets = []
class Tweet:
    def __init__(self,tweetId,userId,clusterId,lat,lon,time):
        self.tweetId = tweetId
        self.userId = userId
        self.clusterId = clusterId
        self.lat = lat
        self.lon = lon
        self.timestamp = time
        time_tuple = re.split(r'[ ]',time)
        self.date = time_tuple[0]
        self.time = time_tuple[1]
        time_tuple = re.split(r':',self.time)
        self.hour = time_tuple[0]
        self.minute = time_tuple[1]
        self.second = time_tuple[2]


class ActivityNode:
    def __init__(self, record):
        self.userId = record[0]
        self.cid = record[1]
        self.posLon = record[2]
        self.posLat = record[3]
        self.x = record[4]
        self.y = record[5]
        self.placeType = record[6]
        self.poiList = record[7]
        self.typeCount = record[8]
        self.weekday_hours = record[9]
        self.weekend_hours = record[10]
        self.weekday_hours_all = record[11]
        self.weekend_hours_all = record[12]
        self.dow_duration = record[13]
        self.max_nexttime = record[14]
        self.avg_nexttime = record[15]
        self.max_nextdist = record[16]
        self.avg_nextdist = record[17]
        self.max_speed = record[18]
        self.avg_speed = record[19]


class Location:
    def __init__(self,userId,lon,lat,placeType):
        self.userId = userId
        self.lon = lon
        self.lat = lat
        self.placeType = placeType


class Graph:
    def __init__(self,users,tweetTable,skipHubs):
        self.nodes = {}
        for user in users:
            userId = user.userId
            sps = readStaypoints(userId,tweetTable)
            tweets = readTweets(userId,tweetTable)
            trajectories = getDailyTrajectories(tweets, sps)
            if skipHubs == 1:
                # Do not Skip transportation hubs
                self.createGraphWithHubs(userId, trajectories)
            elif skipHubs == 2:
                # Skip transportation hubs
                self.createGraphWithoutHubs(userId, trajectories)
            elif skipHubs == 3:
                # Skip transportation hubs and other place labels
                self.createGraphWithoutHubsAndOthers(userId, trajectories)
            
    def createGraphWithHubs(self, userId, trajectories):
        for trajectory in trajectories:
            if len(trajectory) == 0:
                continue
            lastCid = trajectory[0]
            for cid in trajectory:
                if cid != lastCid:
                    self.addTransCount(userId, lastCid, cid)
                lastCid = cid
        
    def createGraphWithoutHubs(self, userId, trajectories):
        for trajectory in trajectories:
            if len(trajectory) == 0:
                continue
            lastCid = trajectory[0]
            for cid in trajectory:
                if self.getTypeByCid(userId, lastCid) is not None:
                    if self.getTypeByCid(userId, cid) is not None:
                        if cid != lastCid:
                            self.addTransCount(userId, lastCid, cid)
                        else:
                            print("skipped!")
                    else:
                        continue
                lastCid = cid

    def createGraphWithoutHubsAndOthers(self, userId, trajectories):
        for trajectory in trajectories:
            if len(trajectory) == 0:
                continue
            lastCid = trajectory[0][0]
            lastId = trajectory[0][1]
            for fp in trajectory:
                cid = fp[0]
                id = fp[1]
                cType = self.getTypeByCid(userId, cid)
                lastCType = self.getTypeByCid(userId, lastCid)
                if lastCType == lastCType and lastCType != 'OTHER':
                    if cType == cType and cType != 'OTHER':
                        if cid != lastCid:
                            self.addTravelDistance(userId, lastCid, cid)
                            self.addTravelTime(userId, lastCid, cid, lastId, id)
                            # self.addTransCount(userId, lastCid, cid)
                        else:
                            print("skipped!")
                    else:
                        continue
                lastCid = cid
                lastId = id
        if userId in self.nodes:
            for orgCid, desCidProperties in self.nodes[userId].items():
                for desCid, properties in desCidProperties.items():
                    duration = np.mean(np.array(properties["endMinute"])) - np.mean(np.array(properties["startMinute"]))
                    properties["duration"] = duration
                    self.nodes[userId][orgCid][desCid]['transCount'] = len(properties["startMinute"])

    def addTravelDistance(self,userId,orgCid,desCid):
        if userId not in self.nodes:
            self.nodes[userId] = {}
        if orgCid not in self.nodes[userId]:
            self.nodes[userId][orgCid] = {}
        if desCid not in self.nodes[userId][orgCid]:
            self.nodes[userId][orgCid][desCid] = {}
        if 'distance' not in self.nodes[userId][orgCid][desCid]:
            orgLat = 0
            orgLon = 0
            desLat = 0
            desLon = 0
            for activityNode in activityNodes:
                if activityNode.userId == userId and activityNode.cid == orgCid:
                    orgLat = activityNode.posLat
                    orgLon = activityNode.posLon
                    continue
                if activityNode.userId == userId and activityNode.cid == desCid:
                    desLat = activityNode.posLat
                    desLon = activityNode.posLon
                    continue
            if orgLat != 0 and orgLon != 0 and desLat != 0 and desLon != 0:
                distance = getDistance(orgLon, orgLat, desLon, desLat)
                self.nodes[userId][orgCid][desCid]['distance'] = distance
            else:
                print("Error: undefined orgLat={}, orgLon={}, desLat={}, or desLon={}".format(orgLat, orgLon, desLat, desLon))
                print("Context: userId={}, orgId={}, desId={}".format(userId, orgCid, desCid))

    def addTravelTime(self,userId,orgCid,desCid,orgId,desId):
        if 'startMinute' not in self.nodes[userId][orgCid][desCid]:
            self.nodes[userId][orgCid][desCid]['startMinute'] = []
            self.nodes[userId][orgCid][desCid]['endMinute'] = []
        for tweetSeries in tweets:
            for tweet in tweetSeries:
                if tweet.tweetId == orgId:
                    startHour = tweet.hour
                    startMinute = tweet.minute
                    startSecond = tweet.second
                    self.nodes[userId][orgCid][desCid]['startMinute'].append(int(startHour)*60 + int(startMinute) + int(startSecond)/60)
                if tweet.tweetId == desId:
                    endHour = tweet.hour
                    endMinute = tweet.minute
                    endSecond = tweet.second
                    self.nodes[userId][orgCid][desCid]['endMinute'].append(int(endHour)*60 + int(endMinute) + int(endSecond)/60)

    def getTypeByCid(self,userId,cid):
        for node in activityNodes:
            if node.userId == userId and node.cid == cid:
                return node.placeType
        return None
            

class User:
    def __init__(self,userId):
        self.userId = userId

    
conn = psycopg2.connect(host="localhost", port=5432, database="madison_gps", user="postgres", password="admin")
cur = conn.cursor()
def readUsers(tweetTable):
    sql = (
        "select distinct subid "
        "from " + tweetTable + " as records " 
    )
    cur.execute(sql)
    users = []
    count=0
    for record in cur:
        count+=1
        record=list(record)
        user = User(record[0])
        users.append(user)
    print("user count: ", count)
    return users


def readActivityNodesFromPg(zoneTable):
    sql = (
        "select user_id, cid, st_x(median_geom) as posLon, st_y(median_geom) as posLat, x, y, placetype_buffer_100 "
        ", poilist, typecount, weekday_hours, weekend_hours, weekday_hours_all, weekend_hours_all, dow_duration"
        ", max_nexttime, avg_nexttime, max_nextdist, avg_nextdist, max_speed, avg_speed "
        "from " + zoneTable + " as activityzones " 
        "where clustername = \'" + clusterName + "\' "
        "order by user_id, cid"
    )
    cur.execute(sql)
    count=0
    for record in cur:
        count+=1
        record=list(record)
        node = ActivityNode(record)
        activityNodes.append(node)
    print("zone count: ", count)

    locations = []
    sql = (
        "select subid, long, lat, placetype "
        "from " + referTable + " as locations " 
        "where geom is not null "
        "order by subid"
    )
    cur.execute(sql)
    for record in cur:
        record=list(record)
        location = Location(record[0], record[1], record[2], record[3])
        locations.append(location)

    pois = pd.DataFrame([vars(l) for l in locations], columns=['userId','lon','lat','placeType'])
    for node in activityNodes:
        node.placeType = findClosestPOI(node.posLon, node.posLat, pois[pois['userId']==node.userId])
    

def readActivityNodesFromCsv():
    nodes_df = pd.read_csv("C:\\Xinyi_Research\\Dissertation\\Proposal\\ModelPrototype\\" + activityzone_file)
    count=0
    for _, row in nodes_df.iterrows():
        node = ActivityNode(row['userId'], row['cid'], row['posLon'], row['posLat'], row['x'], row['y'], row['poiList'], row['typeCount'], row['weekday_hours'], row['weekend_hours'], row['max_nexttime'], row['avg_nexttime'], row['max_nextdist'], row['avg_nextdist'], row['max_speed'], row['avg_speed'], row['placeType'])
        activityNodes.append(node)
        count+=1
    print("zone count: ", count)
    return activityNodes
    

def readTweets(userId, tweetTable):
    timeslots = []
    sql = (
        "select distinct(to_char(time::date, 'YYYY-MM-DD')) as date "
        "from " + tweetTable + " as timeslots " 
        "where subid = " + str(userId) + " "
        "order by date"
    )
    cur.execute(sql)
    for timeslot in cur:
        timeslot=str(timeslot[0])
        timeslots.append(timeslot)

    for i in range(1, len(timeslots)):
        tweetSeries = []
        lastTime = timeslots[i-1]
        time = timeslots[i]
        sql = (
            "select id, subid, lat as y, long as x, time, " + cidName + " as cid "
            "from " + tweetTable + " as records " 
            "where subid = " + str(userId) + " "
            "and time between \'" + lastTime + "\'::timestamp and \'" + time + "\'::timestamp "
            "order by time"
        )
        cur.execute(sql)
        count=0
        for record in cur:
            count+=1
            record=list(record)
            tweet = Tweet(record[0],record[1],record[5],record[2],record[3],record[4].strftime("%m/%d/%Y %H:%M:%S"))
            tweetSeries.append(tweet)
        print("tweet series size: ", count)
        tweets.append(tweetSeries)
    
    return tweets


def readStaypoints(userId, tweetTable):
    sps = []
    sql = (
        "select id, subid, lat as y, long as x, time, " + cidName + " as cid "
        "from " + tweetTable + " as sp " 
        "where type = 'PLACE' "
        "and subid = " + str(userId) + " "
        "order by time"
    )
    cur.execute(sql)
    count=0
    for record in cur:
        count+=1
        record=list(record)
        sp = Tweet(record[0],record[1],record[5],record[2],record[3],record[4].strftime("%m/%d/%Y %H:%M:%S"))
        sps.append(sp)
    print("sp count: ", count)
    return sps


def getDailyTrajectories(tweets, sps):
    clusterSpIds = []
    lastCid = 0
    for tweetSeries in tweets:
        dailyClusterSpIds = []
        for tweet in tweetSeries:
            cid = findClosestSP(tweet.lon, tweet.lat, lastCid, sps)
            if cid != lastCid:
                dailyClusterSpIds.append([cid,tweet.tweetId])
            lastCid = cid
        clusterSpIds.append(dailyClusterSpIds)
    return clusterSpIds


def findClosestSP(lng, lat, cid, sps):
    minDistance = float('inf')
    for sp in sps:
        distance = getDistance(lng, lat, sp.lon, sp.lat)
        if sp.clusterId != 0 and distance < minDistance and distance < 50:
            minDistance = distance
            cid = sp.clusterId
    return cid


def findClosestPOI(lng1, lat1, pois, placetype=None):
    minDistance = float('inf')
    for _, row in pois.iterrows():
        distance = getDistance(lng1, lat1, row['lon'], row['lat'])
        if distance < minDistance and distance < 100:
            minDistance = distance
            placetype = row['placeType']
    return placetype


# Degree to radian
def rad(d):
    return float(d) * math.pi/180.0

# Calculate the distance in meters between two points based on their lat/lon
EARTH_RADIUS=6378.137
def getDistance(lng1,lat1,lng2,lat2):
    radLat1 = rad(lat1)
    radLat2 = rad(lat2)
    a = radLat1 - radLat2
    b = rad(lng1) - rad(lng2)
    s = 2 * math.asin(math.sqrt(math.pow(math.sin(a/2),2) +math.cos(radLat1)*math.cos(radLat2)*math.pow(math.sin(b/2),2)))
    s = s * EARTH_RADIUS
    s = round(s * 10000,2) / 10
    return s


if __name__ == "__main__":
    
    readActivityNodesFromPg(zoneTable)
    columns = [
        'userId','cid','posLon','posLat','x','y',
        'poiList','typeCount','weekday_hours','weekend_hours',
        'weekday_hours_all','weekend_hours_all','dow_duration',
        'max_nexttime','avg_nexttime','max_nextdist','avg_nextdist',
        'max_speed','avg_speed','placeType'
    ]
    activityNodesDf = pd.DataFrame(columns=columns)
    for node in activityNodes:
        nodes = {}
        for column in columns:
            nodes[column] = getattr(node, column)
        activityNodesDf = activityNodesDf.append(nodes, ignore_index=True)
    activityNodesDf.to_csv(activityzone_file, index = False)

    # readActivityNodesFromCsv()

    skipHubs = 3
    users = readUsers(tweetTable)
    batch = 5
    start = 0
    while start < len(users):
        end = start + batch
        user_batch = users[start : end]
        graph = Graph(users=user_batch,tweetTable=tweetTable,skipHubs=skipHubs)
        graphDf = pd.DataFrame(columns=['userId','orgCid','desCid','distance','duration','transCount'])
        for userId in graph.nodes:
            for orgCid in graph.nodes[userId]:
                for desCid in graph.nodes[userId][orgCid]:
                    distance = graph.nodes[userId][orgCid][desCid]['distance']
                    duration = graph.nodes[userId][orgCid][desCid]['duration']
                    transCount = graph.nodes[userId][orgCid][desCid]['transCount']
                    graphDf = graphDf.append({'userId':userId,'orgCid':orgCid,'desCid':desCid,'distance':distance,'duration':duration,'transCount':transCount}, ignore_index=True)
        out = f'graph_{skipHubs}_users{start}-{end-1}.csv' 
        graphDf.to_csv(out, index = False) 
        start = end